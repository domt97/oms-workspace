---
name: sa-messaging-events
description: Messaging rules — transactional outbox with Debezium, Kafka topics and keys, consumer retries, idempotent consumers, schema evolution, SQS triggers. Use when a change publishes or consumes a message.
user-invocable: false
---
# Messaging & events

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
5. **Decide what a failure means.** A poison message must not be silently lost: say whether it should retry, go to a DLT, or be skipped with an alert.
   Configure a `DefaultErrorHandler` with `ExponentialBackOff` and a `DeadLetterPublishingRecoverer` (`<Topic>.DLT`), mark non-retryable exceptions, and classify failures, because one retry policy for all of them loses data:
   - **poison** (unreadable JSON, contract violation, ownership mismatch, constraint error): will never succeed → DLT at once;
   - **infrastructure down** (no DB connection, cannot create a transaction): only waiting fixes it → retry **without limit**
     (bounded backoff); never dead-letter, or an outage silently drops events — and without a replay tool nobody notices;
   - **transient** (deadlock, lock timeout): a few retries with backoff, then DLT.
   A working example is named in `references/current-state.md`.
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

## Current state and known gaps
Not in this file. When you need how the OMS does this today, or which gaps are known, read
`.claude/skills/sa-messaging-events/references/current-state.md`. It is a snapshot: `architecture/generated/` and the code win.
