---
name: change-event
description: Steps to add or change an event or command between OMS services, across the workspace, the producer, the development repo and each consumer. Use when a change publishes, consumes or reshapes a message.
---
# Add or change an event or command

A message crosses repos, so the order matters. Rules: `sa-messaging-events`; tests: `sa-testing-strategy`.
One PR per repo (`/ship` for each service), in the rollout order of step 7.

1. **Contract first** (oms-workspace). Add or edit `architecture/contracts/events/<Name>.schema.json`. Its `description`
   must say "Published by <service>" — the contract check in `scripts/extract_facts.py` reads that line. A change to an
   existing payload only **adds optional fields**. Removing, renaming or retyping a field is a new message name.
2. **Producer.** Declare the type where outgoing messages live — `application/event` or `domain/event` — and write the
   outbox row in the **same transaction** as the business change. Never publish to Kafka from a use case (system rule 2).
3. **Topic and connector** (`repos/development`). Topic name = message type, key = aggregate id (system rule 8, ADR 0002):
   add it to `docker/kafka/create-topics.sh`. A service that publishes for the first time needs its own connector in
   `docker/kafka-connect/connectors/` and an entry in `register-connectors.sh` (`docs/connectors.md`).
4. **Each consumer.** Its own DTO in `infrastructure/message/dto`, mapped to a command (anti-corruption layer). Say what
   makes a redelivery safe (system rule 7), what a poison message does (retry, dead letter), and check the merchant.
5. **Contract tests.** A service that tests against a copy of the schema (inventory-service:
   `src/contractTest/resources/contracts/events/`) gets the new copy in its PR; the copy must equal the workspace file.
6. **Docs** (oms-workspace, same piece of work): the row in `architecture/integration.md`, ownership in `domain-map.md`,
   the flow if the sequence changed. Run `python3 scripts/extract_facts.py`: the generated file must list the message and
   show no "Contract check failed" or "No contract schema" note.
7. **Rollout order.** Consumers that tolerate the new shape ship first, then the producer. For a new message: topic,
   then consumer, then producer.

Done when: schema merged, producer and every consumer have a test with an old and a new payload, generated facts are clean.
