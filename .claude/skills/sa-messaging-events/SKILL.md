---
name: sa-messaging-events
description: Event-driven integration in the OMS — transactional outbox with Debezium, Kafka topics/keys/partitions and ordering, consumer error handling and retries, idempotent consumer pattern, event schema evolution, SQS/EventBridge triggers. Use for any change that publishes or consumes an event or message, or when analysing redelivery, duplicates or lost messages.
---
# Messaging & events

## OMS today (verified in code)
**Publishing — transactional outbox + CDC (ADR 0001, 0002)**
- Use case writes the business rows and an `outbox_events` row in the **same transaction** (`stores-service/.../CreateStoreProductUseCaseService.java`, built by `OutboxEventHelper`).
- `outbox_events` (`stores-service/.../db/migration/V7__add_outbox_events_table.sql`): `aggregate_type`, `aggregate_id`, `event_type`, `payload JSONB`, `status`.
- Debezium `EventRouter` reads the WAL: **topic = `event_type`**, **key = `aggregate_id`** (`route.topic.replacement=${routedByValue}`).
- Rows are inserted with `status = PENDING` and **never updated or deleted** — the table grows forever (gap).

**Consuming — Kafka (inventory-service)**
- `ProductCreatedConsumer`: `@KafkaListener(topics = "ProductCreated", groupId = "product-consumer")`; value is a JSON string inside JSON (Connect JsonConverter), decoded twice.
- `application.yaml` sets only bootstrap servers, group id, `auto-offset-reset: earliest`, String deserializers. **No `CommonErrorHandler` / `DefaultErrorHandler` bean, no dead-letter topic** (searched all `src/main`).
- Therefore the spring-kafka default applies (Spring Boot 3.2.3 → spring-kafka 3.1): `DefaultErrorHandler` with `FixedBackOff(0, 9)` = **10 attempts with no delay, then the record is logged and skipped** (offset committed). It does **not** block the partition forever; a failing record is effectively lost.
- Delivery is **at-least-once** (Debezium + Kafka): every consumer must be idempotent (workspace rule 7).

**Consuming — SQS (inventory-service)**
- `SqsReservationExpireConsumer`: `@SqsListener` with `maxConcurrentMessages = 1`, `maxMessagesPerPoll = 1`, `messageVisibilitySeconds = 90` (Spring Cloud AWS 3.1.1; defaults would be 10/10 and the queue's 30 s). EventBridge sends a tick every minute (`development/docker/infra/local/main.tf`); the body is ignored. The `Sqs_Msa_SentTimestamp` header (`SqsHeaders.MessageSystemAttributes.SQS_SENT_TIMESTAMP`) is used to drop ticks older than `app.reservation-expiry.max-tick-age` when the instance swept recently (fails open otherwise).
- Default acknowledgement is on success: if the listener throws, the message is not deleted and reappears after the visibility timeout. The Terraform queue has **no redrive policy / DLQ**.

## Rules
1. **Never publish to Kafka from a use case.** Write to the outbox in the same transaction. A producing service needs its own outbox table + Debezium connector.
2. **Topic = PascalCase event type, unique across OMS; key = aggregate id.** Same key ⇒ same partition ⇒ processed **in order, one at a time per consumer group**. This is the first concurrency guarantee to reason about.
3. **Every consumer is idempotent.** Pick the mechanism explicitly:
   | Situation | Mechanism |
   |---|---|
   | Consumer creates rows that have a natural key | check-then-insert for the missing keys + unique constraint as backstop (or `INSERT … ON CONFLICT DO NOTHING`) |
   | Consumer changes state | guarded transition (`UPDATE … WHERE status = 'X'`), treat 0 rows as "already done" when that is the meaning |
   | Side effects with no natural key | processed-event table keyed by `eventId` (`INSERT` in same tx; duplicate ⇒ skip) |
4. **Idempotent consumer pattern (OMS standard):**
   - empty input → return early, call no repository;
   - load what already exists in **one** query;
   - skip existing items, log at `info` (`skipping existing …`);
   - existing item with conflicting data (other product/merchant) → log `warn`, do not overwrite;
   - write only the missing items; do not call the write with an empty list;
   - the unique constraint stays as the last line of defence.
5. **Decide what a failure means.** A poison message must not be silently lost: say whether it should retry, go to a DLT, or be skipped with an alert. Today the answer is "skipped after 10 tries" — call that out when it matters.
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
- No DLT / custom error handler on Kafka consumers; no DLQ on SQS.
- `outbox_events` is never cleaned up.
- `OrderCreatedEventConsumer` exists but its listener is commented out.
- `ProductCreatedEvent` DTO duplicated in producer and consumer; no Schema Registry subject although Schema Registry runs locally.
- Consumer group name `product-consumer` is generic.
