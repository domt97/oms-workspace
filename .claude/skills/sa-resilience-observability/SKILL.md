---
name: sa-resilience-observability
description: Resilience and observability in the OMS — failure modes of dependencies (Postgres, Kafka, SQS, S3, other services), timeouts, retries with backoff, dead-letter handling, graceful shutdown, health checks, structured logging, correlation ids, metrics and alerts. Use when a change calls a dependency, consumes messages, runs a job, or when asking "how would we notice and recover if this fails?".
---
# Resilience & observability

## OMS today (verified in code)
**Failure handling**
- **Kafka** (`ProductCreatedConsumer`): no custom error handler. The spring-kafka default `DefaultErrorHandler` retries 10 times with no backoff, then logs and skips the record. There is no DLT (open question 17). The consumer is idempotent (inventory-service#24), so retries are safe.
- **SQS** (`SqsReservationExpireConsumer`):
  - acknowledges on success; a throw makes the message reappear after the 90 s visibility timeout (listener and Terraform);
  - there is no DLQ or redrive policy (open question 18);
  - stale ticks are dropped (inventory-service#28).
- **Expiry** isolates failures per inventory (`REQUIRES_NEW`); a failing inventory is logged and retried next tick.
- **S3** (`S3Config`): SDK defaults as well.
- **Excel import**:
  - `ImportProductService` catches any exception and returns `ImportResult{status: FAILED}` with HTTP 200;
  - validate, products and outbox rows run in **one transaction** on `StoreProductImportHandler.execute` (the S3 read stays outside), so FAILED means nothing was written. The catch stays outside the transaction: a catch-all inside it would commit products without their events.

**Observability**
- **No Spring Boot Actuator, no Micrometer, no tracing** in either service (`build.gradle`). So there are no health/readiness endpoints, no metrics and no trace ids.
- Logging:
  - plain-text Logback defaults;
  - `oms-core` `RequestResponseLoggingFilter` logs each request and response line (method, URI, status, duration, headers redacted);
  - there is no correlation/request id and no MDC.
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
10. **Outbox health**: alert on outbox rows older than N minutes that are not yet published (Debezium down), and on connector status.

## Checklist
- [ ] Failure table: dependency → failure → behaviour → recovery → how we notice.
- [ ] Timeouts and retry policy for each new call; idempotency of what is retried.
- [ ] DLQ/DLT for new consumers; poison-message test.
- [ ] Partial failure: consistent end state (single transaction or compensation)?
- [ ] Logs with ids, correct level, no PII; correlation id carried across.
- [ ] Metric + alert that would reveal this feature failing or falling behind.
- [ ] Shutdown/redeploy mid-run: what happens?

## Known gaps
- No Actuator/metrics/tracing/correlation id; ERROR logging for 4xx; `show_sql` on.
- No Kafka DLT (open question 17), no SQS DLQ (open question 18).
- Import failures returned as 200 FAILED, with database error text in the message (open question 24).
- No timeouts configured for AWS SDK clients; no graceful shutdown.
