---
name: sa-performance-scalability
description: Volume rules — bounded work, paging, batching, N+1, pools, scaling consumers and jobs, back-pressure. Use when a feature reads or writes many rows, runs on a schedule or consumes a stream.
user-invocable: false
---
# Performance & scalability

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

## Current state and known gaps
Not in this file. When you need how the OMS does this today, or which gaps are known, read
`.claude/skills/sa-performance-scalability/references/current-state.md`. It is a snapshot: `architecture/generated/` and the code win.
