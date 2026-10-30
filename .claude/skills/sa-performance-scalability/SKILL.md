---
name: sa-performance-scalability
description: Performance and scalability in the OMS — sizing a feature for large volume, bounded work, paging (offset vs keyset), batching, N+1, connection pools, horizontal scaling of consumers and jobs, back-pressure and capacity estimates. Use whenever a feature reads or writes many rows, runs on a schedule, consumes a stream, or must work with many merchants/stores/orders.
---
# Performance & scalability

## OMS today (verified in code)
**Database access**
- Hikari pool **10** connections per service (`spring.datasource.hikari.maximum-pool-size`, both `application.yaml`).
- `open-in-view: false`, `hibernate.default_batch_fetch_size: 50`, `jdbc.batch_size: 50`, `in_clause_parameter_padding: true`.
- `show_sql: true` is set in both services. It prints every SQL statement to stdout, bypassing the logger. It is noise and a cost under load.
- `StoreProductEntity` collections use `@BatchSize(50)`, and `SpringDataStoreRepository` uses an `@EntityGraph` for address/config/businessHours. Both avoid N+1.

**Paging**
- Product search uses offset paging: `PageRequest`, which also runs a `COUNT(*)` (`oms-core/.../util/PageUtils.java`, `StoreProductPersistenceAdapter.searchProducts`).
- `pageSize` has **no upper bound** (`StoreProductController.getStoreProducts`, `@RequestParam(defaultValue = "10") Integer pageSize`).
- `GET /v1/inventory/inventories/stock-movements/{inventoryId}` returns **every** movement of an inventory, with no paging. `stock_movements` is append-only, so this response grows forever.

**Bulk paths**
- Excel import (`stores-service/.../impex/product/StoreProductImportHandler.java`) reads the whole file from S3 into memory. It validates, saves all products and all outbox rows in one transaction (one Hikari connection held throughout), synchronously inside the HTTP request. There is no row limit (open question 24).
- Reservation expiry (inventory-service#28) is the reference pattern for bounded work:
  - keyset pages `(expires_at, id)` of 500;
  - a 40 s time budget per tick;
  - a partial index `WHERE status = 'RESERVED'`;
  - one tick at a time per instance.

  Its limits are open question 22: `markExpired` issues one statement per row, instances do not split the work, and there are no metrics.

**Per-request remote calls**
- Merchant checks are a primary-key lookup on `merchants` in the same Postgres database (no remote call).

**Kafka**
- `ProductCreatedConsumer` uses the default listener concurrency of 1. Throughput is bounded by the number of partitions × consumer instances.

## Rules
1. **Size it first.** Before designing, write down the volumes: rows per merchant/store, requests or events per second at peak, growth per month. Then estimate cost per unit (DB round trips, remote calls) × volume. If a number is a guess, label it as an estimate and say how to measure it.
2. **Every loop over data is bounded.** Use pages with a fixed size, a time or row budget per run, and leave the rest for the next run. Never "load all matching rows" on a table that grows with business volume.
3. **Keyset paging for jobs and large lists** (`WHERE (k1, k2) > (:k1, :k2) ORDER BY k1, k2 LIMIT n`).
   - Offset paging is acceptable only for small, user-facing lists, and it needs a max page size.
   - Avoid `COUNT(*)` on large tables when the UI does not need a total.
4. **Set-based SQL over row-by-row.**
   - Use one `UPDATE … WHERE id = ANY(:ids) AND <guard> RETURNING id` instead of N single-row updates.
   - Insert in JDBC batches. Batching is disabled for `IDENTITY` ids; sequence or UUID ids batch.
5. **Index for every new query**, matching its `WHERE` and `ORDER BY`.
   - Use a partial index for "active" subsets (status filters).
   - Keep the status as a SQL literal so the planner can use a partial index.
6. **Horizontal scaling must be designed, not assumed.** For each job or consumer, ask: with N instances, do they split the work or repeat it?
   - **Split** via Kafka partitions, `SELECT … FOR UPDATE SKIP LOCKED LIMIT n`, or hash buckets per instance.
   - **Serialise** via a single-flight lock only when the work cannot be split.
7. **Connection budget.** Instances × Hikari pool must stay below Postgres `max_connections` minus headroom. Long transactions and remote calls inside a transaction hold connections; keep both out.
8. **Bulk operations leave the request thread** when they can exceed a few seconds:
   - accept → return 202 + a job id;
   - process in chunks with a transaction per chunk;
   - report progress.
9. **Cache only what is read far more than written**, and state its invalidation (e.g. reference data with a short TTL). Never cache stock quantities.
10. **Measure.** A design for volume names its metrics: throughput, latency p95/p99, backlog, oldest unprocessed age. It also names the alert threshold.

## Checklist
- [ ] Volumes and growth written down; capacity estimate with units (rows/s, round trips per item).
- [ ] Every query: index named, bounded result (`LIMIT` / page size cap), no unbounded `IN (…)`.
- [ ] Every loop/job: page size, budget, what happens to the rest, behaviour after downtime (backlog).
- [ ] N instances: split or duplicate work? What prevents duplicates?
- [ ] Transactions: size per transaction, no remote calls inside, connection pool impact.
- [ ] Remote calls per request (S3, other services) — count them; cache or batch?
- [ ] Metrics and alert for backlog/latency; how a growing backlog becomes visible.

## Known gaps
- Unbounded `pageSize` on product search; unpaged stock-movement listing.
- Synchronous, single-transaction Excel import without a row limit.
- Expiry throughput and lack of instance cooperation (open question 22).
- No Micrometer/Actuator in either service, so no metrics exist yet (see `sa-resilience-observability`).
