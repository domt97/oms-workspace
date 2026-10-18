# ADR 0001 — Publish integration events with transactional outbox + Debezium CDC

Status: Accepted (reconstructed from existing code)

## Context
Services own separate databases. A use case must change its own data and notify other contexts
without dual-write inconsistency.

## Decision
Write the event into `outbox_events` in the same DB transaction as the business change. Debezium
reads the Postgres WAL and the `EventRouter` SMT routes rows to Kafka by `event_type`, keyed by `aggregate_id`.

## Consequences
- At-least-once delivery → consumers must be idempotent.
- No Kafka client in producers; Postgres needs `wal_level=logical` and a Debezium user.
- Each producing service needs its own outbox table and connector config.
