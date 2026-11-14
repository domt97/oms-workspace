---
name: new-service
description: Steps to stand up a new OMS service or bounded context, from the decision to the first PR, so that the workspace, the agents and the facts know it. Use when a new context such as order-service is being built.
---
# Stand up a new service

Rules: `sa-ddd-hexagonal`, `sa-messaging-events`, `sa-multitenancy-security`. Decide first, build second.

1. **Decide the context** (oms-workspace, with the user): what it owns in `architecture/domain-map.md`, its place in
   `vision.md`, and an ADR if a system rule is touched. Business rules it needs must be ✅ or 🟢; ask about the rest.
2. **Contracts before code**: the messages it sends and receives (`/change-event` step 1) and the endpoints it offers.
3. **Repository**: same layout as the existing services — `domain` ← `application` ← `infrastructure` — pinned
   `coreVersion`, `master` and `develop` with `develop` as default branch, the CI workflows of an existing service, and its
   own `CLAUDE.md` (owns, layout, invariants, checklist, known gaps).
4. **Data**: its own Postgres database (system rule 1) with Flyway from `V1`, and an `outbox_events` table if it publishes.
5. **Local infra** (`repos/development`): the database, its topics in `docker/kafka/create-topics.sh`, its outbox
   connector in `docker/kafka-connect/connectors/` and `register-connectors.sh`.
6. **Workspace**: add the repo to `repos.txt`, run `./scripts/sync-repos.sh` and `python3 scripts/extract_facts.py`, and
   check that `architecture/generated/<service>.md` appears and lists what the service publishes. Add the repository row
   and port in `CLAUDE.md`.
7. **Agent**: a `<context>-expert` in `.claude/agents/` modelled on `inventory-expert` (sonnet, preloads only
   `sa-analysis-checklist`), and its name in `oms-architect`'s delegation step.
8. **Web**: if oms-web has a browser-local stand-in for this context, plan its replacement with `web-expert`.

Done when a fresh clone can run the service locally, CI is green, and the generated facts show no contract note.
