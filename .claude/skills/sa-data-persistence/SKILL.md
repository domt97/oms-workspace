---
name: sa-data-persistence
description: Data and persistence in the OMS — PostgreSQL schema, constraints and indexes, Flyway migrations (including zero-downtime expand/contract), JPA/Hibernate pitfalls, native conditional updates, transactions and their failure semantics. Use for any change that touches tables, migrations, repositories, queries or transaction boundaries.
---
# Data & persistence

## OMS today (verified in code)
- PostgreSQL 16, one database + schema per service (`store`, `inventory`). Spring Data JPA / Hibernate 6.4, Flyway.
- Migrations: `src/main/resources/db/migration/V<n>__<what>.sql` — stores-service up to `V8`, inventory-service `V1`.
- Every table has `tenant_id` (workspace rule 4).
- Inventory constraints (`inventory-service/.../V1__init_inventory_tables.sql`):
  - `inventories`: `UNIQUE (store_id, sku)` (`uk_inventory_store_sku`), indexes on store, sku, (store, product).
  - `stock_reservations`: indexes on `order_id`, `inventory_id`, `status` — **no unique constraint on `(order_item_id, inventory_id)`** (root of open question 13).
  - `stock_movements`: append-only audit, sequence with cache.
- Stock quantities change only through **native conditional UPDATEs** in `SpringDataInventoryRepository` (`reserve`, `confirm`, `release`, `stockIn`, `stockOut`), each guarded by a `WHERE` (e.g. `(quantity - reserved_quantity) >= :quantity`) and checked via the returned row count.
- Reservation status changes use a **native guarded UPDATE per row** (`SpringDataStockReservationRepository.transitionStatus`: `WHERE id = :id AND status = :from`), called by `markConfirmed` / `markExpired` (`@Transactional(MANDATORY)`); the row count says who won. It bypasses the persistence context — entities loaded earlier in the same transaction keep the old status. No `@Version` on any entity.
- `createBatch` uses `saveAllAndFlush`.
- Tests are Mockito-only: **native SQL and constraints are not exercised by any test.**

## Rules
1. **Migrations are immutable** once merged. New change ⇒ new `V<next>__<what>.sql`. Check the highest existing version on `develop` first.
2. **Zero-downtime (expand → migrate → contract)** for anything a running version still reads:
   - add column nullable (or with default) → deploy code that writes it → backfill → add `NOT NULL`/constraint in a later migration;
   - rename = add new + dual-write + switch reads + drop old later; never rename in place;
   - adding a unique constraint on existing data: first check/clean duplicates in the migration or a prior step, or the deploy fails.
   - large-table indexes: `CREATE INDEX CONCURRENTLY` must run outside a transaction (Flyway script config `executeInTransaction=false`).
3. **Constraints are the last line of defence**, not the application check. Uniqueness and FK-like rules that matter for correctness get a DB constraint.
4. **Quantity / counter / state changes under concurrency use a conditional UPDATE**, not load-modify-save:
   `UPDATE … SET x = x - :q WHERE id = :id AND <guard>` → `0 rows` means "rule violated or already done". Same for state machines: `… SET status = 'CONFIRMED' WHERE id = :id AND status = 'RESERVED'`.
5. **In PostgreSQL a failed statement aborts the whole transaction.** You cannot `catch` a duplicate-key exception and keep writing in the same transaction. Avoid the error (check first / `ON CONFLICT DO NOTHING`) or let it propagate and retry in a new transaction.
6. **Transaction boundary = the `@UseCase` service method.** Keep it short; no remote calls (HTTP, AWS) inside it. Isolation is the default `READ COMMITTED` — do not assume repeatable reads.
7. **JPA pitfalls**: N+1 on lazy collections; `saveAll` on detached entities issues a SELECT per row; `IN (:list)` with very large lists — chunk; native queries bypass the persistence context (flush/clear when mixing). Declared `@Query` methods do **not** inherit `SimpleJpaRepository`'s class-level `readOnly = true`, and a read-only flag is ignored anyway when joining the caller's read-write transaction — don't cite it as a reason; a `@Modifying` query outside any transaction throws `TransactionRequiredException`.
8. **Queries need indexes** matching their `WHERE`/`ORDER BY`; say which index serves a new query.

## Checklist
- [ ] Next migration version, and is it backward compatible with the currently deployed code?
- [ ] New/changed constraints and what existing data could violate them.
- [ ] Every concurrent write path: conditional UPDATE or constraint? What does `0 rows` mean?
- [ ] Transaction boundary and what is inside it (no remote calls).
- [ ] Index for each new query.
- [ ] How the SQL is verified, given unit tests do not run it (manual check against local Postgres, or a Testcontainers test).

## Known gaps
- No `@Version` / optimistic locking anywhere (state is guarded with conditional UPDATEs instead).
- No integration tests against a real database.
