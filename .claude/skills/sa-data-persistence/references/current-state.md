# Data & persistence — how the OMS does it today (snapshot)

Moved out of `SKILL.md` so the rules load without it. This is a hand-written snapshot, not a rule: before relying on
a line, check it against `architecture/generated/<service>.md` and the code — code wins. A gap listed here without an
open-question number is not yet in `architecture/open-questions.md`.

## OMS today (verified in code)
- PostgreSQL 16, one database + schema per service (`store`, `inventory`). Spring Data JPA / Hibernate 6.4, Flyway.
- Migrations: `src/main/resources/db/migration/V<n>__<what>.sql` — stores-service up to `V10`, inventory-service `V5`.
- `merchant_id`: every inventory-service table has it (except `debezium_heartbeat`, a table of the connector setup, not of the domain: no merchant data, not managed by Flyway); in stores-service (except `debezium_heartbeat`, same as inventory's) only `stores` does and child tables are scoped by `store_id` by design (`sa-multitenancy-security` rule 1).
- Inventory constraints (`inventory-service/.../db/migration/V1`..`V5`):
  - `inventories`: `UNIQUE (store_id, sku)` (`uk_inventory_store_sku`), indexes on store, sku, (store, product).
  - `stock_reservations`: indexes on `inventory_id`, `status`, plus partial `idx_stock_reservation_expiry (expires_at, id) WHERE status = 'RESERVED'` (V2, serves the expiry keyset query — keep `status = 'RESERVED'` a SQL literal there, a bound parameter stops the planner using a partial index under generic plans); `UNIQUE (order_id, order_item_id)` (`uk_stock_reservation_order_item`, V4, one reservation per order line, BR-INV-07; it serves lookups by order and replaced V1's plain `order_id` index).
  - `stock_reservation_orders` (V4): one header per order (`order_id` PK, merchant, store, status, `restock`, JSONB `rejection`) with CHECKs tying `rejection` to REJECTED and `restock` to REJECTED/CANCELLED; written only by native SQL (`INSERT … ON CONFLICT DO NOTHING`, `SELECT … FOR UPDATE` scoped by merchant/store, guarded `UPDATE … AND status = :expected`). Postgres checks the CHECKs on the proposed row **before** `ON CONFLICT`, so an invalid row fails even when the header exists (the domain record enforces them).
  - `outbox_events` (V5): PK `id` = eventId, `merchant_id`, JSONB `payload` and `correlation_context`; rows inserted (JDBC batch) and deleted in the same transaction, so the table is always empty; no index beyond the PK.
  - `stock_movements`: append-only audit, sequence with cache; `reservation_id` (V4, not mapped in JPA) with the partial unique index `uk_stock_movement_reservation_type (reservation_id, type) WHERE reservation_id IS NOT NULL`, written by a set-based `INSERT … SELECT … ON CONFLICT (reservation_id, type) WHERE reservation_id IS NOT NULL DO NOTHING`.
- Stock quantities change only through **native conditional UPDATEs** in `SpringDataInventoryRepository` (`reserve`, `confirm`, `release`, `stockIn`, `stockOut`), each guarded by a `WHERE` (e.g. `(quantity - reserved_quantity) >= :quantity`) and checked via the returned row count.
- Reservation status changes use a **native guarded UPDATE per row** (`SpringDataStockReservationRepository.transitionStatus`: `WHERE id = :id AND status = :from`), called by `markConfirmed` / `markExpired` / `markReleased` / `markReturned` (`@Transactional(MANDATORY)`); the row count says who won. It bypasses the persistence context — entities loaded earlier in the same transaction keep the old status. No `@Version` on any entity.
- `createBatch` uses `saveAllAndFlush`.
- Nullable binds in native SQL are cast (`CAST(CAST(:restock AS TEXT) AS BOOLEAN)`, `CAST(:reason AS VARCHAR)`): Hibernate may bind an untyped null as bytea.
- Tests: inventory-service has an `integrationTest` suite (Testcontainers Postgres, Flyway V1..V5) covering its native SQL, constraints, JSONB and locks (`sa-testing-strategy`); stores-service SQL is exercised by no test.

## Known gaps
- No `@Version` / optimistic locking anywhere (state is guarded with conditional UPDATEs instead).
- No integration tests against a real database in stores-service.
