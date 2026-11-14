# Resilience & observability — how the OMS does it today (snapshot)

Moved out of `SKILL.md` so the rules load without it. This is a hand-written snapshot, not a rule: before relying on
a line, check it against `architecture/generated/<service>.md` and the code — code wins. A gap listed here without an
open-question number is not yet in `architecture/open-questions.md`.

## OMS today (verified in code)
**Failure handling**
- **Kafka** (`ProductCreatedConsumer`, `ProductUpdatedConsumer`, and the stock command consumers `ReserveStockConsumer` / `ConfirmStockReservationConsumer` / `ReleaseStockReservationConsumer`): `KafkaErrorHandlingConfig` sends contract errors to `<topic>.DLT` at once, retries database connection failures without limit and other failures 6 times before the DLT. DLT records keep their headers (incl. `correlationContext`); there is no alerting or replay tool (open questions 17, 40). The consumers are idempotent (catalog: version gate; stock commands: order header), so retries are safe. A stock command's timeouts get the bounded retries (a cancelled statement, SQLState 57014, is excluded from the connection failures); a command in a DLT gets no reply.
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
  - **MDC** (oms-core `logging`): every line is prefixed with `[%X]` (`logging.pattern.correlation`). REST: `RequestIdFilter` keeps a valid `X-Request-Id` (`^[A-Za-z0-9._-]{1,64}$`) or generates a UUID, echoes it, puts `requestId`; `MdcRequestFieldsInterceptor` adds the path/query values configured in `app.logging.mdc.fields` (`MdcProperties`: format `uuid`/`code`/`pattern` (linear regex, values ≤ 64), sources `path`/`query` (raw query string only; caller-chosen, never for tenant ids), `propagate`; oms-core defaults for the common ids, services merge their own; a value failing its format or containing control characters is skipped; a broken entry, a case-only duplicate (env-var override) or a request source on a reserved key (`requestId`, `eventId`, `kafka*`, `sqsMessageId`) fails startup). Kafka listeners open `KafkaMdc.open(record, mdcPropagation)` (`requestId` from the producer's `correlationContext` header — ADR 0004, validated by `MdcPropagation.restore` — else `topic-partition-offset`; plus `eventId`, `merchantId`, `storeId` and `productId` or — stock commands — `orderId` from the payload); the SQS tick uses its message id; expiry adds `inventoryId` per inventory. In application code only `MdcScope` writes MDC (snapshot/restore); the oms-core filter and interceptor manage their own keys; there is no executor/`@Async`, so no `TaskDecorator` yet;
  - the `requestId` crosses services in the outbox → Kafka header `correlationContext` (ADR 0004); only correlation keys (`propagate: true`, no request source) travel; outbound HTTP between services does not carry it yet (no client adapter);
  - user-controlled text in log lines (query names/values, header values, the `logError` message argument, the Kafka DLT line) goes through `LogSanitizer.escape`; stack traces still print raw exception messages (logging 4xx without a stack trace, open question 47, would remove most of them).
- `GlobalExceptionHandler.logError` logs **every** handled exception at ERROR with a stack trace, including 404 and 400. Real errors drown in client mistakes.
- `hibernate.show_sql: true` prints all SQL to stdout.
- There is no `server.shutdown: graceful`; consumers and in-flight requests are cut on stop.

## Known gaps
- No Actuator/metrics/tracing; requestId not propagated over outbound HTTP (no client adapter yet); ERROR logging for 4xx; `show_sql` on (prints SQL to stdout without MDC).
- Kafka DLTs exist but have no alerting or replay (open question 17); no SQS DLQ (open question 18).
- Import failures are 200 FAILED (by design, BR-CAT-13); a client must read `status`, not the HTTP code.
- No timeouts configured for AWS SDK clients; no graceful shutdown.

## Outbox kind and heartbeat (moved from rule 10)
- Both outboxes are delete-after-insert: inventory, and stores-service since stores-service#59.
- Slot lag is a health signal only while the heartbeat works (both connectors: `heartbeat.action.query` into `debezium_heartbeat`; proven locally by Verify f in `development` `docs/connectors.md`, *First application* 2026-11-09 for inventory and 2026-11-11 for stores). Task `RUNNING` does not prove the heartbeat: Debezium 2.2 is expected to only log most heartbeat query failures (not tested yet: First application 2026-11-09; runbook test in `development` `docs/connectors.md`) — also alert on `max(beat_at)` (open question 55).
