# OMS Workspace — System Map

Multi-tenant SaaS **Order Management System**. Each bounded context lives in its own GitHub repo;
this workspace holds the cross-repo knowledge (architecture, contracts, flows) and clones every
repo into `repos/` so Claude can reason about the whole system.

> First time / repos missing? Run `./scripts/sync-repos.sh`.

## Repositories

| Repo | Path | Role | Port |
|------|------|------|------|
| `stores-service` | `repos/stores-service` | Store bounded context: stores, own products (SKU, images), collections, business hours, availability. Publishes `ProductCreated` via outbox. | 8048 |
| `inventory-service` | `repos/inventory-service` | Inventory bounded context: stock per (store, SKU), reservations, stock movement audit. | 8058 |
| `oms-core` | `repos/oms-core` | Shared kernel (Gradle composite build): typed IDs, `AggregateRoot`, `Money`/`Address`, exceptions, `@UseCase`/`@WebAdapter`/`@PersistenceAdapter`, DynamoDB tenant info, S3, Excel import template. | – |
| `development` | `repos/development` | Local infra: docker-compose (Kafka, Kafka Connect + Debezium, Schema Registry, Postgres 16, Redis, LocalStack) and Terraform for LocalStack (S3, SQS, EventBridge). | – |

Not built yet but referenced in code: **order-service** (`OrderCreated` producer), **promotion-service** (`PromotionServiceClient`).

## Where to look

| Need | File |
|------|------|
| Big picture, tech stack, conventions | `architecture/system-overview.md` |
| Who owns what (entities, tables, APIs, events) | `architecture/domain-map.md` |
| Every event and REST endpoint between services | `architecture/integration.md` |
| End-to-end flows | `architecture/flows/*.md` |
| Why things are the way they are | `architecture/adr/*.md` |
| Terms (SKU, reservation, movement…) | `architecture/glossary.md` |
| Known gaps and doc/code drift | `architecture/open-questions.md` |
| How to work inside one service (layout, checklist, invariants) | `repos/<service>/CLAUDE.md` |

## System rules (do not violate when designing features)

1. **Database per service.** stores → Postgres DB `store`, inventory → DB `inventory`. Never query or join across.
2. **Cross-service writes go through events**, published with the **transactional outbox + Debezium CDC** (`outbox_events` table). Never publish to Kafka directly from a use case.
3. **Hexagonal / DDD in every service**: `domain` (pure Java) ← `application` (use cases, ports) ← `infrastructure` (adapters). External event DTOs live in `infrastructure/message/dto` (anti-corruption layer) and are mapped to commands.
4. **Multi-tenant**: `TenantId` is part of every aggregate and every table. Tenant metadata lives in DynamoDB (`tenant_info`).
5. **Aggregates reference each other by typed ID only** (`StoreId`, `ProductId`, `SKU`… from `oms-core`).
6. Shared types go to `oms-core` only if they are truly cross-context; otherwise keep them in the owning service.
7. Consumers must be **idempotent** (Debezium gives at-least-once delivery).
8. **Kafka topic name = event type** (`ProductCreated`), key = aggregate id. Event type names are unique across services (ADR 0002).

## How to analyse a feature

1. Read `domain-map.md`, `integration.md` and the relevant flow **before** opening code.
2. List the bounded contexts affected and why.
3. Only then go into `repos/<service>`: read its `CLAUDE.md` first, then `application/usecase` and `domain/model`.
4. Check `open-questions.md` — docs in service READMEs may be out of date; **code wins**.
5. Use the `/feature-impact` skill for the standard output format; for multi-service features use the `oms-architect` agent, which delegates to the domain experts.

## Build & run

- Java 17, Spring Boot 3.2.3, Gradle. Each service `includeBuild('../oms-core')`, so **all repos must be siblings** — `repos/` keeps that layout.
- Infra: `cd repos/development/docker && docker compose up -d`, then Terraform in `repos/development/docker/infra/local`.
- Service: `./gradlew bootRun --args='--spring.profiles.active=localdev'`. Swagger at `/swagger-ui.html`.

## Keeping this map true

When a change adds/changes a REST endpoint, event, table or aggregate, update `domain-map.md`
and `integration.md` in the same piece of work.
