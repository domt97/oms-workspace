---
name: sa-messaging-events
description: Event-driven integration in the OMS — transactional outbox with Debezium, Kafka topics/keys/partitions and ordering, consumer error handling and retries, idempotent consumer pattern, event schema evolution, SQS/EventBridge triggers. Use for any change that publishes or consumes an event or message, or when analysing redelivery, duplicates or lost messages.
---
# Messaging & events

## OMS today (verified in code)
**Publishing — transactional outbox + CDC (ADR 0001, 0002)**
- Use case writes the business rows and an `outbox_events` row in the **same transaction** (`stores-service/.../CreateStoreProductUseCaseService.java`, built by `OutboxEventHelper`).
- `outbox_events` (`stores-service/.../db/migration/V7__add_outbox_events_table.sql`): `aggregate_type`, `aggregate_id`, `event_type`, `payload JSONB`, `correlation_context`; since stores-service#59 a native INSERT with `id = eventId` then DELETE in the **same transaction** (`OutboxEventPersistenceAdapter`, like inventory's) — always empty; `postgres-cdc` reads it through the insert-only publication of `development` `sql/store-outbox-cdc.sql`, with a heartbeat into `store.debezium_heartbeat` (development#8); `status`/`retry_count` columns are dead (open question 56).
- inventory-service `outbox_events` (V5) for the stock replies: native INSERT with `id = eventId` (header `id`), then DELETE in the **same transaction** — the table stays empty, Debezium publishes from the WAL (`OutboxEventPersistenceAdapter`, one write point per use case via `StockReplyFactory`). Payloads are plain JSON (no typed-id objects), checked against copies of the contract schemas. Published by the connector `inventory-outbox-cdc` (development#7): insert-only publication (`publish = 'insert'`, created by script; the DELETEs never reach Debezium), heartbeat table `inventory.debezium_heartbeat` so the slot advances between replies, topics pre-created with 6 partitions by `docker/kafka/create-topics.sh`.
- Debezium `EventRouter` reads the WAL: **topic = `event_type`**, **key = `aggregate_id`** (`route.topic.replacement=${routedByValue}`). Connector config: `development/docker/kafka-connect/connectors/postgres-cdc.json` and `inventory-outbox-cdc.json` + `register-connectors.sh` (secrets via `FileConfigProvider`).
- Every record carries the optional header `correlationContext` (JSON of the producer's propagated MDC keys, from `outbox_events.correlation_context`, ADR 0004). Consumers restore it with oms-core `MdcPropagation.restore` (validated, never throws) inside `KafkaMdc`. A new outbox column placed by the connector needs the ordered rollout in `development/docs/connectors.md` (migration → slot past it → connector), or the task fails and all events stop.

**Consuming — Kafka (inventory-service)**
- `ProductCreatedConsumer` (`ProductCreated`, group `product-consumer`) and `ProductUpdatedConsumer` (`ProductUpdated`, group `inventory-product-updated`); value is a JSON string inside JSON (Connect JsonConverter), decoded twice (`OutboxPayloadDecoder`).
- Stock command consumers (ADR 0006): `ReserveStockConsumer`, `ConfirmStockReservationConsumer`, `ReleaseStockReservationConsumer` (topic = command name; groups `inventory-reserve-stock`, `inventory-confirm-stock-reservation`, `inventory-release-stock-reservation`; `max.poll.records=5`, concurrency from `app.kafka.stock-commands.concurrency`). They only map and call the use case (idempotent by the order header) inside the `KafkaMdc` scope. Lessons kept in `StockCommandMapping`: check `eventType` against the topic when payloads of different messages overlap; map a missing id to a null wrapper (typed ids accept null); do not let Jackson coerce where a wrong value changes the outcome (`quantity` as `BigDecimal` → whole number required, `restock` as `Object` → JSON boolean required).
- `KafkaErrorHandlingConfig` (`DefaultErrorHandler` bean): contract errors (JSON, `InvalidCatalogEventException`, `InvalidStockCommandException`, ownership mismatch of a catalog event or a stock command, `DataIntegrityViolationException`) go to `<topic>.DLT` at once; database connection failures are retried without limit (backoff up to 1 min); other failures — also a stock command's lock / statement / transaction timeout — are retried 6 times, then sent to the DLT. A cancelled statement (SQLState 57014) is never a connection failure, although Spring JDBC translates SQLState class 57 to `DataAccessResourceFailureException` (classify by the cause chain's SQLState, and prove it with the real exception: `StockCommandErrorClassificationIT`). The recoverer logs the DLT line inside `KafkaMdc`.
- Delivery is **at-least-once** (Debezium + Kafka): every consumer must be idempotent (workspace rule 7).

**Consuming — SQS (inventory-service)**
- `SqsReservationExpireConsumer`: `@SqsListener` with `maxConcurrentMessages = 1`, `maxMessagesPerPoll = 1`, `messageVisibilitySeconds = 90` (Spring Cloud AWS 3.1.1; defaults would be 10/10 and the queue's 30 s). EventBridge sends a tick every minute (`development/docker/infra/local/main.tf`); the body is ignored. The `Sqs_Msa_SentTimestamp` header (`SqsHeaders.MessageSystemAttributes.SQS_SENT_TIMESTAMP`) is used to drop ticks older than `app.reservation-expiry.max-tick-age` when the instance swept recently (fails open otherwise).
- Default acknowledgement is on success: if the listener throws, the message is not deleted and reappears after the visibility timeout. The Terraform queue has **no redrive policy / DLQ**.

## Rules
1. **Never publish to Kafka from a use case.** Write to the outbox in the same transaction. A producing service needs its own outbox table + Debezium connector.
2. **Topic = PascalCase event type, unique across OMS; key = aggregate id.** Same key ⇒ same partition ⇒ processed **in order, one at a time per consumer group**. This is the first concurrency guarantee to reason about.
   **Commands** between services (ADR 0006, e.g. `ReserveStock`) follow the same rules: sent through the sender's outbox, topic = command name, key = the saga's aggregate id; the executor answers with reply events from its own outbox (`causationId` = the command's `eventId`). Business outcomes are replies, contract errors go to the DLT. Different commands of one aggregate sit on different topics, so they can arrive out of order: the executor must accept any order (per-aggregate header with a tombstone).
3. **Every consumer is idempotent.** Pick the mechanism explicitly:
   | Situation | Mechanism |
   |---|---|
   | Consumer creates rows that have a natural key | check-then-insert for the missing keys + unique constraint as backstop (or `INSERT … ON CONFLICT DO NOTHING`) |
   | Consumer changes state | guarded transition (`UPDATE … WHERE status = 'X'`), treat 0 rows as "already done" when that is the meaning |
   | Side effects with no natural key | processed-event table keyed by `eventId` (`INSERT` in same tx; duplicate ⇒ skip) |
   | Command consumer (ADR 0006) | per-aggregate header row locked first (`INSERT … ON CONFLICT DO NOTHING` + `SELECT … FOR UPDATE`); a duplicate changes nothing and re-publishes its reply |
4. **Idempotent consumer pattern (OMS standard):**
   - empty input → return early, call no repository;
   - load what already exists in **one** query;
   - skip existing items, log at `info` (`skipping existing …`);
   - existing item with conflicting data (other product/merchant) → log `warn`, do not overwrite;
   - write only the missing items; do not call the write with an empty list;
   - the unique constraint stays as the last line of defence.
5. **Decide what a failure means.** A poison message must not be silently lost: say whether it should retry, go to a DLT, or be skipped with an alert. Today inventory's Kafka listeners classify failures (`KafkaErrorHandlingConfig`, see above): poison → `<topic>.DLT` at once, database down → retried until it is back, anything else → 6 retries then the DLT; nobody is alerted about a DLT record yet (open question 17) — call that out when it matters.
   When a DLT is added, classify failures, because one retry policy for all of them loses data:
   - **poison** (unreadable JSON, contract violation, ownership mismatch, constraint error): will never succeed → DLT at once;
   - **infrastructure down** (no DB connection, cannot create a transaction): only waiting fixes it → retry **without limit**
     (bounded backoff); never dead-letter, or an outage silently drops events — and without a replay tool nobody notices;
   - **transient** (deadlock, lock timeout): a few retries with backoff, then DLT.
   Reference: inventory-service `KafkaErrorHandlingConfig` (`setBackOffFunction` for connection failures).
6. **Event schema evolution** (recommended, not yet formalised in OMS): only additive, optional fields; never rename/remove/retype a field; a breaking change is a **new event type**. Producer and consumer DTOs are separate classes — change both and update `architecture/contracts/events/<Event>.schema.json`.
7. **Payload = facts at the time of the event**, with `eventId`, `occurredAt`, `merchantId`. Consumers must not call back the producer synchronously to "complete" the event.

## Checklist
- [ ] Topic, key and therefore ordering scope of every event touched.
- [ ] Who else consumes this topic (`architecture/integration.md`)? Does the change break them?
- [ ] Idempotency mechanism of each consumer (rule 3) and the duplicate scenario that proves it.
- [ ] Failure path: what happens on exception — retries, skip, DLT? Is data lost?
- [ ] Failures classified (poison → DLT now, infrastructure down → retry without limit, transient → retries then DLT), each with a test.
- [ ] Outbox row written in the same transaction as the business change?
- [ ] Contract files updated (JSON Schema, `integration.md`).

## Known gaps
- Kafka DLT topics have no alerting and no replay tool (open questions 17, 40); no DLQ on SQS.
- Both outboxes are always empty: a lost or recreated replication slot loses the gap's events for good (no resync tool, open question 40; runbooks in `development` `docs/connectors.md`).
- The stock command topics have no producer yet (order-service is not built); a command in a DLT gets no reply.
- `ProductCreatedEvent` DTO duplicated in producer and consumer; no Schema Registry subject although Schema Registry runs locally.
- Consumer group name `product-consumer` is generic.
