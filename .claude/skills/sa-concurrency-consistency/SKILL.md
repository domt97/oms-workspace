---
name: sa-concurrency-consistency
description: Concurrency control and cross-service consistency in the OMS — race analysis, conditional updates vs locks, idempotency keys, state machines, reservation with TTL, sagas (choreography vs orchestration) and compensation, eventual consistency. Use when two actors can touch the same data, when designing a multi-step or multi-service flow (e.g. order → stock reservation), or when reviewing for oversell/double-processing.
---
# Concurrency & consistency

## OMS today (verified in code)
**Inventory concurrency mechanisms**
- Stock quantities: conditional UPDATEs (`inventory-service/.../SpringDataInventoryRepository.java`), e.g. reserve only if `quantity - reserved_quantity >= :q`; services check the row count (`ReserveStockService`, `ConfirmStockReservationService`, `ExpireByInventoryTransaction`). This is what prevents oversell.
- Kafka ordering: events keyed by aggregate id are processed sequentially per partition (see `sa-messaging-events`).
- Expiry: EventBridge tick every minute → SQS → `ExpireStockReservationService` loads `RESERVED` reservations past `expires_at`, groups by inventory, runs `ExpireByInventoryTransaction` with `REQUIRES_NEW` per inventory; a failing inventory is logged (`Reservation expiry failed for inventory {}`) and the loop continues.
- Reservation status: guarded per-row `UPDATE stock_reservations SET status = :to WHERE id = :id AND status = 'RESERVED'` (`StockReservationRepository.markConfirmed` / `markExpired`, ascending id, returns the ids that won). Only winners change `reserved_quantity`. Confirm: all `CONFIRMED` → no-op; any `EXPIRED`/`RELEASED` → reject; lost update → throw and roll back. Expire: losers are skipped.
- Lock order for every writer: reservation rows by id ascending, then inventory rows sorted with Java `UUID.compareTo` (`ReserveStockService`, `ConfirmStockReservationService`).

**Known races / non-idempotent paths**
- **ReserveStock replay**: no unique key on `(order_item_id, inventory_id)` → the same order item can be reserved twice (open question 13).
- **Already-corrupted `reserved_quantity`** (from before the guard): that inventory's release returns 0 rows, rolls back and logs an error on every tick until repaired with a reconciliation query.
- Reserve/confirm/expire do not write `StockMovement` (open question 14).

## Rules
1. **Start every design with the race table**: list each actor that can touch the same row (consumer instances, REST, scheduled job, retries/redelivery) and, for each pair, what prevents a bad interleaving.
2. **Prefer atomic conditional statements over locks**:
   - quantities: `SET x = x ± :q WHERE id = :id AND <invariant>`;
   - state machines: `SET status = :new WHERE id = :id AND status = :expected` — the row count tells you who won;
   - inserts: unique constraint (+ check-first or `ON CONFLICT DO NOTHING`).
   Use `SELECT … FOR UPDATE` (pessimistic) only when several rows must be read and changed together; keep it short and lock in a consistent order to avoid deadlocks. Use `@Version` (optimistic) for aggregates edited by users/REST.
   **Lock order is global**: when a fix sorts rows to avoid deadlocks, apply the same order to *every* writer of those tables (reserve, confirm, expire, adjust…), not only the one being changed. Sort typed IDs with an explicit comparator (`Comparator.comparing(InventoryId::getValue)`) — oms-core IDs (`BaseId`) are not `Comparable`, so a bare `TreeMap`/`sorted()` throws `ClassCastException`.
3. **Every state transition is guarded in the database**, not only in the domain object. The domain method states the rule; the guarded UPDATE enforces it under concurrency.
4. **Idempotency key per business operation**: what makes "the same request" recognisable? (order item id, event id, request id). Back it with a unique constraint.
5. **Partition key ≠ global serialisation.** Ordering holds only within one key/partition and one consumer group. Anything else (REST, jobs, other topics) can still race.
6. **Cross-service consistency is eventual.** No distributed transactions. Use a **saga**:
   - *choreography* (services react to each other's events) for short flows with few steps;
   - *orchestration* (one service — usually the one owning the business process, e.g. order — drives steps and compensations) when there are many steps, timeouts or branching.
   Every step needs a **compensation** and every step + compensation must be idempotent.
7. **Reservations (holds) need a TTL and a single owner of the expiry decision.** Confirm and expire must be mutually exclusive transitions on the same row (rule 3).
8. **Make retries safe before adding them.** A retry on a non-idempotent step multiplies the bug.
9. **Bound the work before adding a lock.** When a job or consumer can overlap with itself and the writes are already guarded,
   overlap costs only redundant work. Limit that work first (keyset pages, a time budget, one message in flight, drop stale triggers);
   add mutual exclusion only if the remaining overlap is still too costly. The user does not want Postgres advisory locks: offer a lease
   row, ShedLock or a FIFO queue as options instead (inventory reservation expiry, inventory-service PR #28).

## Checklist
- [ ] Race table (rule 1) with the mechanism for each pair.
- [ ] Each state change: is it a guarded UPDATE? what does `0 rows` mean (conflict vs already done)?
- [ ] Idempotency key and its unique constraint.
- [ ] For multi-service flows: saga style, owner, each step's compensation, timeout handling.
- [ ] Failure halfway: which steps are done, which are compensated, how the system converges.
- [ ] Audit: does every quantity change write a `StockMovement`?

## Pattern for the order ↔ inventory flow (to apply when order-service is built)
`OrderCreated` → inventory reserves (idempotent on order item) → publishes `StockReserved` / `StockReservationFailed` via its own outbox → order confirms or cancels → inventory confirms / releases with guarded transitions; expiry is the timeout compensation. Inventory has **no outbox yet** — publishing results requires adding one (see `sa-messaging-events`).
