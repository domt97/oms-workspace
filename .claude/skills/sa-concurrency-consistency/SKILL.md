---
name: sa-concurrency-consistency
description: Concurrency and cross-service consistency rules — races, conditional updates vs locks, idempotency, state machines, reservations, sagas. Use when two actors can touch the same data or a flow spans services.
user-invocable: false
---
# Concurrency & consistency

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

## Checklist
- [ ] Race table (rule 1) with the mechanism for each pair.
- [ ] Each state change: is it a guarded UPDATE? what does `0 rows` mean (conflict vs already done)?
- [ ] Idempotency key and its unique constraint.
- [ ] For multi-service flows: saga style, owner, each step's compensation, timeout handling.
- [ ] Failure halfway: which steps are done, which are compensated, how the system converges.
- [ ] Audit: does every quantity change write a `StockMovement`?

## Pattern for the order ↔ inventory flow (ADR 0006, `flows/order-stock-reservation.md`)
order-service (saga owner) sends `ReserveStock` / `ConfirmStockReservation` / `ReleaseStockReservation` from its outbox (key `orderId`) → inventory decides each command under the lock of a per-order header (idempotency, tombstone for out-of-order commands), changes stock with guarded updates and replies from **its own outbox** (`StockReserved`, `StockReservationRejected`, …); expiry is the timeout compensation and publishes `StockReservationExpired`. Business outcomes are replies, contract errors go to the DLT. Inventory's replies are written to its outbox in the same transaction as each decision (built; published by the connector `inventory-outbox-cdc`, development#7), and its Kafka command consumers are built (they add no state: a redelivered command is a duplicate for the header); order-service is not. A lost confirm reply can leave the saga stuck (obligation 3, open question 54).

## Current state and known gaps
Not in this file. When you need how the OMS does this today, or which gaps are known, read
`.claude/skills/sa-concurrency-consistency/references/current-state.md`. It is a snapshot: `architecture/generated/` and the code win.
