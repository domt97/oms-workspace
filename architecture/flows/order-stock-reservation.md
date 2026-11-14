# Flow: Order → stock reservation lifecycle

Status: **inventory's side built** (ADR 0006): the use cases, the outbox replies published by the connector
`inventory-outbox-cdc`, and the Kafka command consumers. order-service is not built: nothing sends the commands yet.
Rules: BR-INV-02..05, 07, 08, 11, BR-CAT-04, BR-ORD-07, 09, 12, 14.

## Lifecycle of one reservation (one order line)

```mermaid
stateDiagram-v2
    [*] --> RESERVED: ReserveStock (all lines of the order or none)
    RESERVED --> CONFIRMED: ConfirmStockReservation (order PLACED) → SALE
    RESERVED --> RELEASED: ReleaseStockReservation → RESERVE_RELEASE
    RESERVED --> EXPIRED: TTL (15 min) passed, SQS tick → RESERVE_EXPIRE + StockReservationExpired
    CONFIRMED --> RETURNED: ReleaseStockReservation with restock → RETURN (quantity back)
    CONFIRMED --> [*]: release without restock (goods stay sold)
    RELEASED --> [*]
    EXPIRED --> [*]
    RETURNED --> [*]
```

## Messages

```mermaid
sequenceDiagram
  participant O as order-service (saga owner)
  participant K as Kafka
  participant I as inventory-service
  O->>K: ReserveStock (order outbox, key orderId)
  K->>I: tx: lock order header, guarded reserve per line, RESERVE movements, outbox reply
  I-->>O: StockReserved (expiresAt) | StockReservationRejected (reason per line)
  O->>K: ConfirmStockReservation (when the order is PLACED)
  K->>I: tx: header lock, RESERVED→CONFIRMED, SALE movements, outbox reply
  I-->>O: StockReservationConfirmed | StockReservationConfirmationFailed
  O->>K: ReleaseStockReservation {restock, reason} (cancel, reject, timeout)
  K->>I: tx: RESERVED→RELEASED / CONFIRMED→RETURNED (restock) / keep CONFIRMED, outbox reply
  I-->>O: StockReservationReleased
  Note over I: expiry job: RESERVED→EXPIRED, RESERVE_EXPIRE, StockReservationExpired (no command)
```

## Order header (`stock_reservation_orders`)

One row per order: `merchant_id`, `store_id`, status `RESERVED | REJECTED | CONFIRMED | CANCELLED` (closed), `restock`
(set by the first release), and for `REJECTED` the rejection (`orderReason`, reason per rejected line) so a duplicate
reserve gets the same answer. Every command first takes this row under `FOR UPDATE`, scoped by `(order, merchant, store)`;
a row owned by another merchant/store is a contract error (DLT). A duplicate command changes nothing and re-publishes a
reply for the current state (BR-INV-07).

| Arrives out of order | Result |
|----------------------|--------|
| Release before Reserve (order timed out) | header created `CANCELLED` (tombstone); the late Reserve gets `Rejected{ORDER_CLOSED}`, nothing held |
| Confirm before Reserve | `ConfirmationFailed{UNKNOWN_ORDER}` and a tombstone (`restock` unset); a repeated confirm answers `ORDER_CLOSED`, a later Reserve is rejected `ORDER_CLOSED`, the first release still sets `restock` |
| Release before Confirm | RESERVED lines released, header `CANCELLED`; the late Confirm (also one replayed from a DLT) gets `ConfirmationFailed{ORDER_CLOSED}` |
| Release sent before the Confirmed reply arrived, confirm already applied (reachable only if obligation 3 is relaxed, open question 54) | with `restock`: lines `RETURNED`, stock back, `RETURN` movements; without: lines stay `CONFIRMED` (goods stay sold), header `CANCELLED`. How the saga treats the late `Confirmed`: open question 54 |
| Old command replayed from a DLT | decided by the header and line states; an old `ReserveStock` is also `STALE_COMMAND` |

order-service's obligations (ADR 0006): a saga that sent `ReserveStock` and was not rejected ends confirmed or released, also when no reply arrives (for a confirm step see open question 54); a `StockReserved`
for a closed saga is compensated; no release while a confirm has no reply (obligation 3, under review: open question 54); replies to commands deduplicated by
`(orderId, causationId, eventType)`, `StockReservationExpired` by `eventId`.

Audit note: a confirm that was applied and then cancelled with `restock` writes both a `SALE` and a `RETURN` movement
for goods never handed over; sales reports must net them by `reservation_id`.

### Inventory's guarantee

Any interleaving of confirm and release on one order ends in the state the commands
describe (header lock; no oversell, no double count); whether `restock = false` is right is order-service's choice.
Stock correctness never depends on order-service's timeouts.

## Lost replies (outbox rows are deleted at once, so a reply lost after commit cannot be re-published)

A reply can be lost when the connector's slot is dropped or recreated (open question 55). What brings the saga back:

| Lost reply | Recovery |
|------------|----------|
| `StockReserved` / `StockReservationRejected` | the saga times out and releases (obligation 1), or re-sends the reserve (the duplicate answers the stored outcome) |
| `StockReservationReleased` | inventory's state is already final; obligation 1 is met by the release; a re-send is optional and harmless |
| `StockReservationExpired` | a later confirm answers `NOT_RESERVED`; a release reports the line `EXPIRED` |
| `StockReservationConfirmed` / `StockReservationConfirmationFailed` | open question 54 (re-send the confirm, which is safe, or cancel; decided with order-service) |

## Duplicate commands (BR-INV-07)

A duplicate changes no stock and publishes a reply again (new `eventId`, `causationId` = the duplicate command's
`eventId`). Replies carry no "replayed" flag: order-service deduplicates by `(orderId, causationId, eventType)` and its
saga state (ADR 0006).

| Command | Header / lines found | Reply |
|---------|----------------------|-------|
| `ReserveStock`, same lines | header `RESERVED`, `CONFIRMED` or `CANCELLED` after a successful reserve | `StockReserved` with the lines and `expiresAt` of that reserve (the reserve step's outcome; later changes were reported by their own replies) |
| `ReserveStock`, different lines | header with reservations (compared with `stock_reservations`) | contract error → `ReserveStock.DLT`, nothing published |
| `ReserveStock` (lines not compared: nothing to compare with) | header `REJECTED` | `StockReservationRejected` with the stored reasons (the header keeps the rejection: `orderReason` and the reason per line) |
| `ReserveStock` (lines not compared) | header `CANCELLED` without any reservation (tombstone) | `StockReservationRejected{ORDER_CLOSED}` |
| `ConfirmStockReservation` | all lines `CONFIRMED` | `StockReservationConfirmed` |
| `ConfirmStockReservation` | header `REJECTED` / `CANCELLED`, or a line no longer `RESERVED` | `StockReservationConfirmationFailed` (`ORDER_CLOSED` / `NOT_RESERVED`) with the current line statuses |
| `ReleaseStockReservation` | header `CANCELLED` | `StockReservationReleased` with the current line statuses and the `restock` fixed by the first release (a different `restock` is logged at WARN and ignored) |
| `ReleaseStockReservation` | header `REJECTED` | `StockReservationReleased` with no lines; `restock` = the value stored by the first release (a different `restock` later is logged at WARN and ignored) |

## Reserve (one transaction, all-or-nothing per order, ≤ 100 lines)

1. `SET LOCAL lock_timeout` / `statement_timeout`; insert the header (`ON CONFLICT DO NOTHING`), then lock it by
   `(order, merchant, store)`; not found → owned by another merchant/store → contract error (DLT).
2. Header existed before this command → duplicate: compare the lines and answer from the table above. **This check
   comes before the stale check**, so a successful reserve redelivered after the TTL is not turned into a rejection.
3. Header just created and `occurredAt` older than the TTL (with a clock-skew tolerance) → header `REJECTED`,
   `Rejected{STALE_COMMAND}`.
4. Load inventories by `(merchant, store, sku IN …)`; a missing SKU or another product's SKU → `UNKNOWN_SKU`.
5. Domain pre-check per line in Java UUID order (INACTIVE → `NOT_ORDERABLE`, not enough → `INSUFFICIENT_STOCK`);
   any failure → header `REJECTED` (reasons stored) + reply, no update run.
6. Guarded `reserve … AND status = 'ACTIVE'` per line; at the first 0-row update, release the lines already held in
   this transaction, read the reasons with a scalar projection, header `REJECTED` (reasons stored) + reply.
7. Otherwise insert reservations (TTL from configuration, default 15 min), `RESERVE` movements, header `RESERVED`,
   outbox `StockReserved`.

## Timeouts (how they surface, and how the error handler must treat them)

Each command transaction sets `lock_timeout` 3 s and `statement_timeout` 5 s (`SET LOCAL`) and has a 10 s transaction
timeout (`app.reservation.*`; `StockCommandTransactionIT` asserts that reserve / confirm / release take it from the property). All
three are transient, not contract errors: retried with a bounded backoff like other failures in `KafkaErrorHandlingConfig`,
then `<topic>.DLT` (decided 2026-11-08: unlimited retries would block the order's partition if a command times out every
time; a command in a DLT is covered by ADR 0006 — the saga times out and releases (for a confirm step see open question
54), the hold TTL is the last net). Never
dead-lettered at once like a contract error. As asserted by `StockConcurrencyIT`:
`lock_timeout` → `PessimisticLockingFailureException` (SQLState 55P03); `statement_timeout` → Spring
`QueryTimeoutException` (57014); a query created after the deadline → `TransactionTimedOutException`. Not covered by a
test: Hibernate also gets the deadline in whole seconds and may refuse a statement (or the flush at commit) in the last
second with `org.hibernate.TransactionException` (likely translated to `JpaSystemException`), and a statement running at
the deadline is cancelled by the JDBC query timeout (57014). No timeout-specific handling is needed: the default bounded
policy already applies. What matters is that a timeout is never matched as a contract error (DLT at once) or as a
connection failure (unlimited retries). So when the command consumers add their contract exceptions to the not-retryable
list or widen the connection-failure check, a test must show, by cause chain (SQLState 55P03 / 57014,
`TransactionTimedOutException`, a "transaction timeout expired" Hibernate `TransactionException`), that timeouts still get
the bounded retries and then the DLT.

*Covered by tests:* `KafkaErrorHandlingConfigTest` asserts those cause chains, and
`StockCommandErrorClassificationIT` gives the real exceptions to the real error handler: 55P03 and 57014 produced by
Postgres under a use case, and the transaction-deadline exception from a real Spring transaction (not through a use case). That IT found one exception to the paragraph above: the outbox INSERT and DELETE are plain JDBC
(`NamedParameterJdbcTemplate`), not Hibernate, and Spring JDBC translates the whole SQLState class 57 to
`DataAccessResourceFailureException` — so a `statement_timeout` (57014) on those statements was classified as a
connection failure (unlimited retries). `isConnectionFailure` now excludes SQLState 57014 by the cause chain: a
cancelled statement always gets the bounded retries; other class-57 states (e.g. 57P01, admin shutdown) stay
connection failures. The Hibernate `TransactionException` case is asserted with a constructed exception only.

## Command consumers (inventory-service)

`ReserveStockConsumer`, `ConfirmStockReservationConsumer`, `ReleaseStockReservationConsumer` — one topic and one
consumer group each (`inventory-reserve-stock`, `inventory-confirm-stock-reservation`,
`inventory-release-stock-reservation`). Each only decodes the record (JSON string inside JSON, or a plain object), maps
it to the command and calls the use case inside the record's MDC scope (so the reply's `correlation_context` carries
the command's `requestId`; log lines carry `orderId`). They hold no state: idempotency is the order header's.

| Record | What inventory does |
|--------|---------------------|
| Valid command | use case runs; whatever the outcome (also a rejection or a duplicate), the reply is in the outbox and the offset is committed |
| Unreadable JSON, a malformed UUID or instant, a missing required field (only a missing `reason` is accepted), `quantity` not a whole number, `restock` not a JSON boolean, more than 100 lines, the order owned by another merchant/store, the same order with different lines | `<topic>.DLT` at once, nothing written, **no reply** |
| `eventType` different from the topic's message type | `<topic>.DLT` at once. The three payloads overlap: without this check a `ReleaseStockReservation` payload on topic `ConfirmStockReservation` would be read as a confirm and deduct stock. The schemas already fix `eventType` with a `const` |
| Lock / statement / transaction timeout, a confirm or release that lost to the expiry | 6 retries with backoff (~35 s plus the attempts), then `<topic>.DLT`; the retry of a lost race answers from the new state |
| Database unreachable | retried without limit (backoff up to 1 min); the partition waits |
| Null value (tombstone) | ignored with a WARN |

Not checked: that the record key equals `orderId` (inventory's correctness does not depend on partition order).
Jackson's lenient readings are accepted: a numeric `occurredAt` is epoch **seconds**, a `quantity` sent as the string
`"5"` is 5. A command in a DLT gets no reply and is visible only as one ERROR line until the DLT tooling exists (open
question 17); the saga's timeout covers it (ADR 0006; for a confirm step see open question 54).

Listener sizing: 5 records per poll and one listener thread per topic per instance by default
(`app.kafka.stock-commands.concurrency`); the reasoning and the pool rule are in inventory-service `CLAUDE.md`,
production sizing is open question 30.

Verified by hand on the local stack (2026-11-12, messages sent with `kafka-console-producer`, no order-service):
reserve → duplicate → confirm → release with restock produced `StockReserved` ×2, `StockReservationConfirmed`,
`StockReservationReleased` on their topics with the command's `requestId` in the `correlationContext` header; not enough
stock → `StockReservationRejected`; bad JSON and a wrong `eventType` → the DLT at once; a confirm while the order header
was locked → 7 attempts in 55 s, then `ConfirmStockReservation.DLT`, no rebalance, later commands processed.

## Locks

Global order: order header → reservations (id ascending) → inventories (Java `UUID.compareTo`). Expiry takes only
reservation → one inventory and never the header, so it cannot form a cycle; confirm × expire and release × expire are
decided by the guarded `status = 'RESERVED'` updates.

## What exists today

| Step | inventory-service code | Entry point |
|------|------------------------|-------------|
| Reserve | `ReserveStockService`: header, duplicate / stale checks, reasons, guarded reserve, `RESERVE` movements → `ReserveStockResult` | `ReserveStockConsumer` (topic `ReserveStock`) |
| Confirm | `ConfirmStockReservationService`: header (tombstone if missing), `SALE` movements → `ConfirmStockReservationResult` | `ConfirmStockReservationConsumer` (topic `ConfirmStockReservation`) |
| Expire | `ExpireStockReservationService` → `ExpireByInventoryTransaction`: `RESERVE_EXPIRE` movements, `StockReservationExpired` per (order, merchant, store) | `SqsReservationExpireConsumer` |
| Release | `ReleaseStockReservationService`: `RESERVE_RELEASE` / `RETURN` movements, `restock` fixed by the first release → `ReleaseStockReservationResult` | `ReleaseStockReservationConsumer` (topic `ReleaseStockReservation`) |

Every result above is written as its reply to `outbox_events` in the same transaction (`StockReplyFactory`,
`OutboxEventPersistenceAdapter`): inserted with `id = eventId` and deleted at once; Debezium publishes it from the
WAL. Published by `inventory-outbox-cdc`.

Still to build: DLT alerting and replay (open questions 17, 40), and order-service itself.
