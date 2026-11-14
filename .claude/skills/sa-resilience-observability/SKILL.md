---
name: sa-resilience-observability
description: Failure and visibility rules — timeouts, retries, dead letters, graceful shutdown, health, logs, correlation ids, metrics. Use when a change calls a dependency, consumes messages or runs a job.
user-invocable: false
---
# Resilience & observability

## Rules
1. **List failure modes per dependency** for every change:
   - **slow**: timeout;
   - **down**: retry, fail, or degrade;
   - **partial**: what happened halfway.

   Say what the user or caller sees and how the system converges.
2. **Timeouts everywhere**: HTTP clients (connect + read), AWS SDK (`apiCallTimeout`, `apiCallAttemptTimeout`), DB (`connection-timeout`; statement timeout for heavy queries). No call without an upper bound.
3. **Retries**:
   - only for idempotent operations;
   - with exponential backoff and jitter, bounded attempts (one exception: a consumer whose database is down, `sa-messaging-events` rule 5);
   - never retry a validation or business error.
   - Message consumers: Kafka failure classes and the DLT are in `sa-messaging-events` rule 5; the SQS dead-letter queue in `sa-aws-platform` rule 3.
4. **Poison messages never block or vanish silently**: after retries they go to a DLQ/DLT with the reason, and someone is alerted.
5. **Don't hide failures.** Returning 200 with `FAILED` in the body, or catch-log-continue, is acceptable only when the caller is told and the state is consistent (all or nothing). Prefer failing the transaction to half-done work.
6. **Graceful shutdown**: `server.shutdown: graceful`, plus listener containers stopping after the in-flight message. Long jobs check a stop/budget signal between pages.
7. **Health**: Actuator liveness and readiness. Readiness includes DB and, if required for serving, Kafka/SQS. Liveness never depends on external systems.
8. **Logs**:
   - one line per business event with ids (`merchantId`, `storeId`, `orderId`, `reservationId`);
   - a correlation id from header or new UUID, put in MDC and propagated to events and outbound calls;
   - client errors (4xx) at WARN or INFO, server errors at ERROR;
   - no PII or secrets (`sa-multitenancy-security` rule 8).
9. **Metrics** (Micrometer when added):
   - per consumer: processed/failed counts, lag;
   - per job: backlog, oldest item age, duration;
   - per endpoint: latency and error rate;
   - business counters (reservations created, expired, oversell attempts rejected).
   - Every metric that indicates a stuck flow has an alert.
10. **Outbox health**, by outbox kind: an outbox that **keeps** rows — alert on rows older than N minutes that are not yet published; a **delete-after-insert** outbox (both services today, `references/current-state.md`) is always empty — alert on replication slot lag (WAL kept) and connector task status instead. Both: alert on connector status. Slot lag is a health signal only while the connector's heartbeat works, and task `RUNNING` does not prove the heartbeat: also alert on the age of the last heartbeat (`max(beat_at)`).

## Checklist
- [ ] Failure table: dependency → failure → behaviour → recovery → how we notice.
- [ ] Timeouts and retry policy for each new call; idempotency of what is retried.
- [ ] DLQ/DLT for new consumers; poison-message test.
- [ ] Partial failure: consistent end state (single transaction or compensation)?
- [ ] Logs with ids, correct level, no PII; correlation id carried across.
- [ ] Metric + alert that would reveal this feature failing or falling behind.
- [ ] Shutdown/redeploy mid-run: what happens?

## Current state and known gaps
Not in this file. When you need how the OMS does this today, or which gaps are known, read
`.claude/skills/sa-resilience-observability/references/current-state.md`. It is a snapshot: `architecture/generated/` and the code win.
