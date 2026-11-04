# ADR 0004 — Carry correlation keys from the outbox to consumers in a Kafka header

Status: Accepted (2026-11)

## Context
Every service logs with an MDC `requestId` (oms-core `RequestIdFilter`; one id per HTTP request, kept from the
browser's `X-Request-Id`). An event produced by stores-service was consumed by inventory under a different id
(`topic-partition-offset`), so one user action could not be followed across services without joining on `eventId`
(open question 46). Correlation is envelope metadata, not part of the event contract (the JSON Schemas in
`contracts/events/` describe the payload only).

## Decision
- The keys marked `propagate: true` in `app.logging.mdc.fields` (oms-core `MdcProperties`) travel with every event.
  Only **correlation keys** may propagate (default: `requestId`; later e.g. a trace id): a key taken from a request
  (entity or tenant ids such as `merchantId`) or a message key (`eventId`, `kafka*`, `sqsMessageId`) fails startup.
- **Producer:** the outbox row stores them in `correlation_context JSONB NOT NULL DEFAULT '{}'` (stores-service V9),
  filled by the persistence adapter with oms-core `MdcPropagation.capture()` from the writing thread's MDC.
  The application layer (`OutboxEventHelper`, use cases, domain) does not know about it.
- **Transport:** Debezium's `EventRouter` places the column in the Kafka header **`correlationContext`**
  (`table.fields.additional.placement=correlation_context:header:correlationContext`, `SimpleHeaderConverter`):
  UTF-8 JSON object of string → string, e.g. `{"requestId":"abc"}`.
- **Consumer:** `MdcPropagation.restore(header)` keeps only keys the consumer itself propagates, never message keys,
  only values passing their format, at most 1 KB; it never throws (a broken header must not send a valid event to the
  DLT). Inventory's `KafkaMdc` sets `requestId` from it, else `topic-partition-offset`; payload ids override header keys.
- The header is optional: consumers must accept it absent, empty or invalid.

## Consequences
- One `requestId` follows a flow from the browser through stores-service to inventory's consumer and DLT lines.
  A Kafka record's position stays in `kafkaTopic`/`kafkaPartition`/`kafkaOffset`; all records of one Excel import share
  the import request's id.
- Adding a propagated key needs no migration and no connector change, but it needs code that puts the key in the MDC
  (propagated keys have no request source), and the same `app.logging.mdc.fields` entry in every consumer (`restore`
  drops keys the consumer does not propagate).
- Each new producing service needs the same column, adapter call and connector placement.
- Adding a placed column to the outbox needs an ordered rollout: migration first, wait until the replication slot
  has passed it, then the connector config (`development/docs/connectors.md`); otherwise the connector task fails and
  all events stop until rollback.
- The header comes from internal topics but is untrusted: a producer to the topic can plant a misleading `requestId`
  in logs (same as `X-Request-Id` over HTTP until authentication exists), never a tenant id.
- Not covered: outbound HTTP between services (no client adapter exists yet; it should send `X-Request-Id` from
  `capture()`), and W3C `traceparent` once tracing exists (it can become a propagated key).
