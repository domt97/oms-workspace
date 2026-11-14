---
name: sa-data-persistence
description: PostgreSQL, Flyway and JPA rules — schema, constraints, indexes, zero-downtime migrations, native updates, transactions. Use when a change touches tables, migrations, repositories, queries or transaction boundaries.
user-invocable: false
---
# Data & persistence

## Rules
1. **Migrations are immutable** once merged. New change ⇒ new `V<next>__<what>.sql`. Check the highest existing version on `develop` first.
2. **Zero-downtime (expand → migrate → contract)** for anything a running version still reads:
   - add column nullable (or with default) → deploy code that writes it → backfill → add `NOT NULL`/constraint in a later migration;
   - rename = add new + dual-write + switch reads + drop old later; never rename in place;
   - adding a unique constraint on existing data: first check/clean duplicates in the migration or a prior step, or the deploy fails.
   - large-table indexes: `CREATE INDEX CONCURRENTLY` must run outside a transaction (Flyway script config `executeInTransaction=false`).
3. **Constraints are the last line of defence**, not the application check. Uniqueness and FK-like rules that matter for correctness get a DB constraint.
4. **Writes that can overlap use a conditional UPDATE**, not load-modify-save. The forms, lock order and what `0 rows` means: `sa-concurrency-consistency` rules 2–3.
5. **In PostgreSQL a failed statement aborts the whole transaction.** You cannot `catch` a duplicate-key exception and keep writing in the same transaction. Avoid the error (check first / `ON CONFLICT DO NOTHING`) or let it propagate and retry in a new transaction.
6. **Transaction boundary = the `@UseCase` service method.** Keep it short; no remote calls (HTTP, AWS) inside it. Isolation is the default `READ COMMITTED` — do not assume repeatable reads.
   - **Self-invocation:** `@Transactional` only applies to a call that goes through the Spring proxy. A method the class (or an oms-core template such as `AbstractImportTemplate.execute`) calls on `this` — `process`, `postImport` — never gets a transaction, whatever its annotation. Either open the transaction in code around the writes with `TransactionTemplate` (stores-service: `StoreProductImportHandler.process` saves products + outbox rows inside `transactionTemplate.execute`), or move the writes to a separate `@Transactional` bean (inventory: `ExpireByInventoryTransaction`). Both use the same transaction manager, propagation and commit/rollback; `TransactionTemplate` also rolls back on checked exceptions and lets a Mockito test verify `commit`/`rollback` on a mock `PlatformTransactionManager`. Keep the writes that must be atomic in one template step (not split between `process` and `postImport`). Without any transaction, each Spring Data call commits on its own.
   - **A catch-all that turns errors into a result stays outside the transaction.** Inside it, an exception thrown outside a repository proxy leaves the transaction committable, and the catch commits the partial work (e.g. products without their outbox rows); one already marked rollback-only ends in `UnexpectedRollbackException` (500). Guard it with a test (the catching service is not annotated).
   - Remote reads (S3, HTTP) go before the transaction. Before claiming what the client sees for their errors, trace each exception to its HTTP status (handler mapping) — they are rarely all 4xx.
7. **JPA pitfalls**: N+1 on lazy collections; `saveAll` on detached entities issues a SELECT per row; `IN (:list)` with very large lists — chunk; `IN (:list)` with an **empty** list in a **native** query renders `IN ()`, a Postgres syntax error (derived `findByXIn` handles it, hand-written SQL does not) — branch on empty before the query and test that branch; native queries bypass the persistence context (flush/clear when mixing). Declared `@Query` methods do **not** inherit `SimpleJpaRepository`'s class-level `readOnly = true`, and a read-only flag is ignored anyway when joining the caller's read-write transaction — don't cite it as a reason; a `@Modifying` query outside any transaction throws `TransactionRequiredException`.
8. **Queries need indexes** matching their `WHERE`/`ORDER BY`; say which index serves a new query.
   - Use a partial index for "active" subsets (status filters).
   - Keep the status as a SQL literal so the planner can use a partial index.

## Checklist
- [ ] Next migration version, and is it backward compatible with the currently deployed code?
- [ ] New/changed constraints and what existing data could violate them.
- [ ] A write path that can overlap with another? Open `sa-concurrency-consistency`.
- [ ] Transaction boundary and what is inside it (no remote calls).
- [ ] The `@Transactional` method is reached through the proxy (not via `this`), and no catch-all converting errors to a result runs inside the transaction.
- [ ] Index for each new query.
- [ ] Every native `IN (:list)`: what happens when the list is empty?
- [ ] How the SQL is verified, given unit tests do not run it (manual check against local Postgres, or a Testcontainers test).

## Current state and known gaps
Not in this file. When you need how the OMS does this today, or which gaps are known, read
`.claude/skills/sa-data-persistence/references/current-state.md`. It is a snapshot: `architecture/generated/` and the code win.
