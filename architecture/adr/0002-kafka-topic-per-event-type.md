# ADR 0002 — One Kafka topic per event type, named exactly after the event

Status: Accepted (confirmed from the running connector `postgres-cdc`, 2026-10-18)

## Context
Debezium's outbox `EventRouter` routes rows from `outbox_events` by a field. By default the topic
would be `outbox.event.<value>`, which leaks the transport into the name and differs per connector.

## Decision
Route by `event_type` and set `transforms.outbox.route.topic.replacement=${routedByValue}`.
The topic name is the event type in PascalCase, e.g. `ProductCreated`. Message key is
`aggregate_id`, so all events of one aggregate land in the same partition (ordered per aggregate).

## Consequences
- Adding an event = choose a unique PascalCase `event_type`; the topic appears automatically
  (broker auto-create) — no connector change needed for a new event in an existing producer.
- Event type names must be unique across all producing services (two services must not both
  publish `ProductCreated` with different meaning). Prefix with the context if ever ambiguous.
- Consumers subscribe by event name (`@KafkaListener(topics = "ProductCreated")`).
- A new producing service needs its own connector (own DB, slot, publication) with the same
  `EventRouter` settings.
