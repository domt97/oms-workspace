---
name: sa-resilience-observability
description: Resilience and observability in the OMS — failure modes of dependencies (Postgres, Kafka, SQS, S3, other services), timeouts, retries with backoff, dead-letter handling, graceful shutdown, health checks, structured logging, correlation ids, metrics and alerts. Use when a change calls a dependency, consumes messages, runs a job, or when asking "how would we notice and recover if this fails?".
---
# Resilience & observability

## OMS today (verified in code)
**Failure handling**
- **Kafka** (`ProductCreatedConsumer`, `ProductUpdatedConsumer`): `KafkaErrorHandlingConfig` sends contract errors to `<topic>.DLT` at once, retries database connection failures without limit and other failures 6 times before the DLT. DLT records keep their headers (incl. `correlationContext`); there is no alerting or replay tool (open questions 17, 40). The consumers are idempotent (version gate), so retries are safe.
- **SQS** (`SqsReservationExpireConsumer`):
  - acknowledges on success; a throw makes the message reappear after the 90 s visibility timeout (listener and Terraform);
  - there is no DLQ or redrive policy (open question 18);
  - stale ticks are dropped (inventory-service#28).
- **Expiry** isolates failures per inventory (`REQUIRES_NEW`); a failing inventory is logged and retried next tick.
- **S3** (`S3Config`): SDK defaults as well.
- **Excel import**:
  - `ImportProductService` checks merchant/store (404), one import per store (409) and a server slot (waits, 503 + Retry-After); the handler's exceptions become `ImportResult{status: FAILED}` with HTTP 200 — rule messages kept, anything else a generic message (details only in the log, WARN for rule failures, ERROR + stack for internal ones);
  - products and outbox rows are written in **one transaction** (`TransactionTemplate` in `StoreProductImportHandler.process`; the S3 read and validation run before it), so FAILED means nothing was written. The catch stays outside the transaction: a catch-all inside it would commit products without their events.

**Observability**
- **No Spring Boot Actuator, no Micrometer, no tracing** in either service (`build.gradle`). So there are no health/readiness endpoints, no metrics and no trace ids.
- Logging:
  - plain-text Logback defaults;
  - `oms-core` `RequestResponseLoggingFilter` logs each request and response line (method, URI, status, duration, headers redacted);
  - **MDC** (oms-core `logging`): every line is prefixed with `[%X]` (`logging.pattern.correlation`). REST: `RequestIdFilter` keeps a valid `X-Request-Id` (`^[A-Za-z0-9._-]{1,64}$`) or generates a UUID, echoes it, puts `requestId`; `MdcRequestFieldsInterceptor` adds the path/query values configured in `app.logging.mdc.fields` (`MdcProperties`: format `uuid`/`code`/`pattern` (linear regex, values ≤ 64), sources `path`/`query` (raw query string only; caller-chosen, never for tenant ids), `propagate`; oms-core defaults for the common ids, services merge their own; a value failing its format or containing control characters is skipped; a broken entry, a case-only duplicate (env-var override) or a request source on a reserved key (`requestId`, `eventId`, `kafka*`, `sqsMessageId`) fails startup). Kafka listeners open `KafkaMdc.open(record, mdcPropagation)` (`requestId` from the producer's `correlationContext` header — ADR 0004, validated by `MdcPropagation.restore` — else `topic-partition-offset`; plus `eventId`, `merchantId`, `storeId`, `productId` from the payload); the SQS tick uses its message id; expiry adds `inventoryId` per inventory. In application code only `MdcScope` writes MDC (snapshot/restore); the oms-core filter and interceptor manage their own keys; there is no executor/`@Async`, so no `TaskDecorator` yet;
  - the `requestId` crosses services in the outbox → Kafka header `correlationContext` (ADR 0004); only correlation keys (`propagate: true`, no request source) travel; outbound HTTP between services does not carry it yet (no client adapter);
  - user-controlled text in log lines (query names/values, header values, the `logError` message argument, the Kafka DLT line) goes through `LogSanitizer.escape`; stack traces still print raw exception messages (logging 4xx without a stack trace, open question 47, would remove most of them).
- `GlobalExceptionHandler.logError` logs **every** handled exception at ERROR with a stack trace, including 404 and 400. Real errors drown in client mistakes.
- `hibernate.show_sql: true` prints all SQL to stdout.
- There is no `server.shutdown: graceful`; consumers and in-flight requests are cut on stop.

## Rules
1. **List failure modes per dependency** for every change:
   - **slow**: timeout;
   - **down**: retry, fail, or degrade;
   - **partial**: what happened halfway.

   Say what the user or caller sees and how the system converges.
2. **Timeouts everywhere**: HTTP clients (connect + read), AWS SDK (`apiCallTimeout`, `apiCallAttemptTimeout`), DB (`connection-timeout`; statement timeout for heavy queries). No call without an upper bound.
3. **Retries**:
   - only for idempotent operations;
   - with exponential backoff and jitter, bounded attempts;
   - never retry a validation or business error.
   - Kafka: configure a `DefaultErrorHandler` with `ExponentialBackOff` and a `DeadLetterPublishingRecoverer` (`<Topic>.DLT`), and mark non-retryable exceptions.
   - SQS: a redrive policy (`maxReceiveCount`) to a DLQ.
4. **Poison messages never block or vanish silently**: after retries they go to a DLQ/DLT with the reason, and someone is alerted.
5. **Don't hide failures.** Returning 200 with `FAILED` in the body, or catch-log-continue, is acceptable only when the caller is told and the state is consistent (all or nothing). Prefer failing the transaction to half-done work.
6. **Graceful shutdown**: `server.shutdown: graceful`, plus listener containers stopping after the in-flight message. Long jobs check a stop/budget signal between pages.
7. **Health**: Actuator liveness and readiness. Readiness includes DB and, if required for serving, Kafka/SQS. Liveness never depends on external systems.
8. **Logs**:
   - one line per business event with ids (`merchantId`, `storeId`, `orderId`, `reservationId`);
   - a correlation id from header or new UUID, put in MDC and propagated to events and outbound calls;
   - client errors (4xx) at WARN or INFO, server errors at ERROR;
   - no PII.
9. **Metrics** (Micrometer when added):
   - per consumer: processed/failed counts, lag;
   - per job: backlog, oldest item age, duration;
   - per endpoint: latency and error rate;
   - business counters (reservations created, expired, oversell attempts rejected).
   - Every metric that indicates a stuck flow has an alert.
10. **Outbox health**, by outbox kind: an outbox that **keeps** rows — alert on rows older than N minutes that are not yet published (note: stores-service rows never leave `PENDING`, so "not published" cannot be measured there today); a **delete-after-insert** outbox (inventory) is always empty — alert on replication slot lag (WAL kept) and connector task status instead. Both: alert on connector status. Slot lag is a health signal only while the heartbeat works (inventory: `heartbeat.action.query` into `debezium_heartbeat`; to be proven by Verify f in `development` `docs/connectors.md`, *Verify inventory-outbox-cdc*; until then slot lag is not a reliable signal). Task `RUNNING` does not prove the heartbeat: Debezium 2.2 is expected to only log most heartbeat query failures (to be confirmed in the connector's *First application*) — also alert on `max(beat_at)` (open question 55).

## Checklist
- [ ] Failure table: dependency → failure → behaviour → recovery → how we notice.
- [ ] Timeouts and retry policy for each new call; idempotency of what is retried.
- [ ] DLQ/DLT for new consumers; poison-message test.
- [ ] Partial failure: consistent end state (single transaction or compensation)?
- [ ] Logs with ids, correct level, no PII; correlation id carried across.
- [ ] Metric + alert that would reveal this feature failing or falling behind.
- [ ] Shutdown/redeploy mid-run: what happens?

## Known gaps
- No Actuator/metrics/tracing; requestId not propagated over outbound HTTP (no client adapter yet); ERROR logging for 4xx; `show_sql` on (prints SQL to stdout without MDC).
- No Kafka DLT (open question 17), no SQS DLQ (open question 18).
- Import failures are 200 FAILED (by design, BR-CAT-13); a client must read `status`, not the HTTP code.
- No timeouts configured for AWS SDK clients; no graceful shutdown.
