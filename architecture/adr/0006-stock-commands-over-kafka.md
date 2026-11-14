# ADR 0006 — Stock commands over Kafka, replies from inventory's outbox

Status: Accepted (2026-11-05). Built in inventory: the use cases (inventory-service#39) and the outbox replies (inventory-service#40); the connector `inventory-outbox-cdc` (development#7); the command consumers (inventory-service `feature/stock-command-consumers`); order-service not built (see `flows/order-stock-reservation.md`). Obligation 3 is under review (open question 54).

## Context
order-service (not built) orchestrates the order saga and "other services execute commands and report back with
events" (BR-ORD-12, Q6). inventory-service already has reserve / confirm / expire logic but no entry point, no release
implementation and no way to publish anything. The alternative of synchronous internal REST calls was considered and
rejected by the product owner (2026-11-05) in favour of messaging, so that order and inventory stay decoupled in time
and every step is durable on both sides.

## Decision
- **Commands** are Kafka messages written by the sender through its own transactional outbox (ADR 0001) and routed
  like events (ADR 0002): topic = message type, key = the saga's aggregate id. Stock commands, key `orderId`:
  `ReserveStock`, `ConfirmStockReservation`, `ReleaseStockReservation` (one topic each). Command names are imperative,
  replies are past tense; all names stay unique across services. Schemas: `contracts/events/*.schema.json`.
- **Replies** are events from the executing service's own outbox, key `orderId`, `aggregate_type = StockReservation`,
  each carrying `causationId` (the command's `eventId`):
  `StockReserved`, `StockReservationRejected`, `StockReservationConfirmed`, `StockReservationConfirmationFailed`,
  `StockReservationReleased`; `StockReservationExpired` is emitted by inventory's expiry job without a command.
- **inventory gets an outbox** (`outbox_events` in DB `inventory`, with `correlation_context` from day one, ADR 0004)
  and a **second Debezium connector** on that database with its own slot and publication. Topics are created with
  partitions **before** the connector is registered (a broker-created topic has 1 partition, and adding partitions
  later moves keys).
- **Business outcomes are replies, not errors.** Insufficient stock, an INACTIVE or unknown SKU, an order already
  closed, a stale reserve: inventory commits a reply and the offset. Contract errors (bad JSON, missing ids, an
  `orderId` owned by another merchant/store, the same order with different lines) go to `<topic>.DLT`.
- **Idempotency and order** (BR-INV-07): inventory keeps one header row per order (`stock_reservation_orders`) and
  decides every command from the header and line states under a row lock. A duplicate command changes no stock and
  publishes its reply again (a new `eventId`; replies have no "replayed" flag); what each duplicate answers is the table *Duplicate
  commands* in `flows/order-stock-reservation.md`. Commands of one order sit on different topics, so they can arrive
  out of order; the header absorbs it: a `ReleaseStockReservation` or a `ConfirmStockReservation` that finds no header
  creates a closed one (tombstone, `restock` unset), so a later `ReserveStock` is rejected `ORDER_CLOSED`, a repeated
  confirm answers `ORDER_CLOSED`, and the first real release still sets `restock`.
- **Obligations of order-service** (the saga owner), part of the contract:
  1. A saga that sent `ReserveStock` and did not get `StockReservationRejected` ends with a confirmed order or with
     `ReleaseStockReservation`, **including when no reply arrives** (command in a DLT, timeout); giving up means sending
     a release, never just stopping (for a confirm step without a reply see open question 54). A confirmed order that is cancelled
     later is released too (with `restock`, BR-ORD-09). After `StockReservationRejected` nothing is held and no release
     is needed (one is harmless).
  2. A `StockReserved` arriving for a saga that is already closed is compensated with a release, not ignored.
  3. No release is sent while a sent `ConfirmStockReservation` has no reply yet. *Under review (open question 54):* with
     only this rule a lost confirm reply leaves the saga with no way out.
  4. Replies to commands are deduplicated by `(orderId, causationId, eventType)` and the saga state, not by `eventId` (a
     re-published reply has a new `eventId`). `StockReservationExpired` has no command (`causationId` null) and is
     never re-published: deduplicate it by `eventId`. An order may get several, each covering some of its lines.
  5. `restock` on a release follows BR-ORD-09.
- inventory rejects a `ReserveStock` whose `occurredAt` is older than the hold TTL (`STALE_COMMAND`, BR-INV-11), with a
  small clock-skew tolerance; the check never applies to confirm or release.

## Alternatives considered
- **Synchronous internal REST** from order-service: simpler and immediate, but couples the saga to inventory's
  availability and needs its own retry/idempotency on HTTP; rejected by the product owner.
- **One `InventoryCommands` topic**: keeps commands of one order in order, but routes by something other than
  `event_type` (breaks ADR 0002) and still needs the header logic for redelivery and DLT replays.
- **Choreography** (inventory reacts to `OrderPlaced` etc.): contradicts BR-ORD-12 (orchestration).

## Consequences
- Checkout latency adds two outbox → Debezium hops (≈ 0.5–2 s estimated); order-service must treat placement as
  asynchronous.
- A command in a DLT gets no reply: the saga notices by timeout and releases (obligation 1; for a confirm step see open
  question 54); the hold TTL is the last safety net.
- Each producing service runs its own connector and replication slot; a stopped connector keeps WAL on that database.
- System rule 8 now covers commands too: topic = message type, unique across services, key = aggregate id.
- Kafka has no ACLs locally; in production only order-service may write the command topics.
- About three replies per order pass through inventory's outbox. The rows are inserted and deleted in the same
  transaction (decided 2026-11-08): Debezium reads the INSERTs from the WAL, the table stays empty,
  and the replication slot (WAL kept, lag) is what must be watched. This holds only if the connector PR proves one
  record per reply, no tombstone and a RUNNING task (proven locally 2026-11-09, development#7 *First application*;
  production slots: open question 55); otherwise rows are kept a few days and removed by a cleanup job.
  A reply lost after commit (slot dropped or recreated) cannot be re-published; recovery per reply type is in the
  flow (*Lost replies*).
