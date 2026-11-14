# Performance & scalability — how the OMS does it today (snapshot)

Moved out of `SKILL.md` so the rules load without it. This is a hand-written snapshot, not a rule: before relying on
a line, check it against `architecture/generated/<service>.md` and the code — code wins. A gap listed here without an
open-question number is not yet in `architecture/open-questions.md`.

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
- Excel import (BR-CAT-13) is bounded: `ProductExcelReader` copies the S3 object (≤ 5 MB) to a temp file and streams only the three import sheets with SAX (row caps 1,000 / 10,000 / 20,000, text and styles budgets); never `XSSFWorkbook`, which loads every cell. The write is one transaction (one Hikari connection), synchronously in the request: measured 6.5 s for a file at the limits, ~15 s for three at once (512 MB heap, ≤ 220 MB used). One import per store; server slots = heap / 128 MB − 1, at most 4 (database pool 10), waiting up to 40 s with at most 20 waiters. Crafted files at every budget: 3 at once ≤ 367 MB of a 512 MB heap.
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
- The stock command listeners (inventory-service) set `max.poll.records=5` and take their concurrency from `app.kafka.stock-commands.concurrency` (default 1). Two rules to reuse: (1) bound one poll below `max.poll.interval.ms` — records × (pool wait + transaction timeout) + the longest backoff, here 5 × 31 s + 60 s = 215 s < 300 s; the pool's connection wait counts **per record** and lies outside the transaction timeout; (2) every listener thread can hold a connection: `3 × concurrency + 3` (catalog listeners, expiry) must stay within the Hikari pool (10), which also serves REST. With concurrency 1 a record being retried delays the other partitions of its topic on that instance.

## Known gaps
- Unbounded `pageSize` on product search; unpaged stock-movement listing.
- Excel import is synchronous (bounded, but long at the limits): move to async (202 + job) if 503s or slow imports show up.
- Expiry throughput and lack of instance cooperation (open question 22).
- No Micrometer/Actuator in either service, so no metrics exist yet (see `sa-resilience-observability`).
