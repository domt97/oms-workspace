# Concurrency & consistency — how the OMS does it today (snapshot)

Moved out of `SKILL.md` so the rules load without it. This is a hand-written snapshot, not a rule: before relying on
a line, check it against `architecture/generated/<service>.md` and the code — code wins. A gap listed here without an
open-question number is not yet in `architecture/open-questions.md`.

## OMS today (verified in code)
**Inventory concurrency mechanisms**
- Stock quantities: conditional UPDATEs (`inventory-service/.../SpringDataInventoryRepository.java`), e.g. reserve only if `quantity - reserved_quantity >= :q`; services check the row count (`ReserveStockService`, `ConfirmStockReservationService`, `ExpireByInventoryTransaction`). This is what prevents oversell.
- Kafka ordering: events keyed by aggregate id are processed sequentially per partition (see `sa-messaging-events`).
- Expiry: EventBridge tick every minute → SQS → `ExpireStockReservationService` pages `RESERVED` reservations past `expires_at` in `(expires_at, id)` keyset order (500 per page, stops starting pages after a 40 s budget), groups each page by inventory, runs `ExpireByInventoryTransaction` with `REQUIRES_NEW` per inventory; a failing inventory is logged (`Reservation expiry failed for inventory {}`) and the cursor moves past it. The tick is only a signal: the consumer takes one at a time per instance and drops stale ones if it swept recently. **No cross-instance lock** — overlapping sweeps are safe because `markExpired` is guarded (deliberate choice: bound the work instead of locking). Throughput limits and the missing backlog metric are open question 22.
- Reservation status: guarded per-row `UPDATE stock_reservations SET status = :to WHERE id = :id AND status = 'RESERVED'` (`StockReservationRepository.markConfirmed` / `markExpired`, ascending id, returns the ids that won). Only winners change `reserved_quantity`. Same for `markReleased` (`RESERVED → RELEASED`) and `markReturned` (`CONFIRMED → RETURNED`). Confirm: header CONFIRMED → `Confirmed`; a line not RESERVED → `ConfirmationFailed{NOT_RESERVED}`; lost update → throw and roll back (the retry answers NOT_RESERVED). Expire: losers are skipped.
- Stock commands (ADR 0006): every reserve / confirm / release first `SET LOCAL lock_timeout`/`statement_timeout`, inserts the order header `stock_reservation_orders` (`ON CONFLICT DO NOTHING`) and locks it `FOR UPDATE` by (order, merchant, store); duplicates and out-of-order commands are decided from the header and line states under that lock (BR-INV-07; duplicate check before stale check; tombstones; first release fixes `restock`). Every hold change writes a movement idempotently (`ON CONFLICT (reservation_id, type) DO NOTHING`).
- Lock order for every writer: order header → reservation rows by id ascending (release: RESERVED ids, then CONFIRMED ids — two disjoint sets) → inventory rows sorted with Java `UUID.compareTo` (reserve sorts lines; confirm and release use a `TreeMap`, one pass). The expiry never takes the header (reservations → one inventory). Races are covered by `StockConcurrencyIT`.

**Known races / non-idempotent paths**
- **Already-corrupted `reserved_quantity`** (from before the guard): that inventory's release returns 0 rows, rolls back and logs an error on every tick until repaired with a reconciliation query.
