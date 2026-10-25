# OMS Workspace — System Map

Multi-tenant marketplace **Order Management System** (like Shopee): **tenant = market** (country/region, fully isolated); inside a tenant, **merchants** (sellers, often chains) run **stores**, and customers buy across merchants. Each bounded context lives in its own GitHub repo;
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
| Product vision, subdomains, bounded contexts (built + planned), context map, roadmap | `architecture/vision.md` |
| Business rules (✅ in code / 🟡 proposed / ❓ open) and open business questions | `architecture/business-rules.md` |
| Big picture, tech stack, conventions | `architecture/system-overview.md` |
| Who owns what (entities, tables, APIs, events) | `architecture/domain-map.md` |
| Every event and REST endpoint between services | `architecture/integration.md` |
| End-to-end flows | `architecture/flows/*.md` |
| Why things are the way they are | `architecture/adr/*.md` |
| Terms (SKU, reservation, movement…) | `architecture/glossary.md` |
| **Extracted facts (generated from code, ground truth)** | `architecture/generated/<service>.md`, `facts.json` |
| Known gaps and doc/code drift | `architecture/open-questions.md` |
| How to work inside one service (layout, checklist, invariants) | `repos/<service>/CLAUDE.md` |
| Solution-architect knowledge (DDD, messaging, data, concurrency, performance/scale, API design, multi-tenancy/security, resilience/observability, testing, AWS platform, analysis checklist) | `.claude/skills/sa-*/SKILL.md` |

## System rules (do not violate when designing features)

1. **Database per service.** stores → Postgres DB `store`, inventory → DB `inventory`. Never query or join across.
2. **Cross-service writes go through events**, published with the **transactional outbox + Debezium CDC** (`outbox_events` table). Never publish to Kafka directly from a use case.
3. **Hexagonal / DDD in every service**: `domain` (pure Java) ← `application` (use cases, ports) ← `infrastructure` (adapters). External event DTOs live in `infrastructure/message/dto` (anti-corruption layer) and are mapped to commands.
4. **Multi-tenant (tenant = market)**: every aggregate root belongs to exactly one tenant — directly (`tenant_id`) or through an immutable parent (`store_id` → store → merchant → tenant). **Nothing crosses tenants.** Inside a tenant, merchant-owned data (merchant, store, catalog, inventory, order) is also scoped by merchant/store for merchant users, and customer-owned data (cart, checkout, payment) by customer. Every query filters by tenant **and** owner (merchant/store or customer) — never by id alone. Market config lives in DynamoDB (`tenant_info`); the merchant level is not in code yet (open question 28).
5. **Aggregates reference each other by typed ID only** (`StoreId`, `ProductId`, `SKU`… from `oms-core`).
6. Shared types go to `oms-core` only if they are truly cross-context; otherwise keep them in the owning service.
7. Consumers must be **idempotent** (Debezium gives at-least-once delivery).
8. **Kafka topic name = event type** (`ProductCreated`), key = aggregate id. Event type names are unique across services (ADR 0002).

## How to analyse a feature

1. Read `vision.md`, `business-rules.md`, `domain-map.md`, `integration.md` and the relevant flow **before** opening code.
   Design only on business rules marked ✅ or confirmed by the user; for 🟡/❓ rules **ask the user** (quote the id) — never invent business rules.
2. List the bounded contexts affected and why.
3. Only then go into `repos/<service>`: read its `CLAUDE.md` first, then `application/usecase` and `domain/model`.
4. Check `open-questions.md` — docs in service READMEs may be out of date; **code wins**.
5. Use the `/feature-impact` skill for the standard output format; for multi-service features use the `oms-architect` agent, which delegates to the domain experts.
6. Every analysis or plan must pass `sa-analysis-checklist`; have it challenged by the `plan-reviewer` agent before presenting it.

## How to implement a change

Use the `/ship <service> <feature|fix> <slug>` skill for any implementation in a service: it branches
from `develop`, plans with the domain expert (user approves), implements, runs `./gradlew test`,
reviews, updates docs, and — after asking — commits, pushes and opens a PR **into `develop`**.
For changes spanning several services, run `/feature-impact` first, then one `/ship` per service.

## Git workflow

- Service repos (`stores-service`, `inventory-service`): `master` is the release branch; **`develop`** is the
  integration branch and the GitHub default branch (new PRs and clones target `develop`).
  Branch features/fixes **from `develop`** and open PRs **into `develop`**; `master` only receives `develop` via release PRs.
- `oms-workspace`: `master` is protected. Every change (docs, agents, skills, scripts, workflows)
  goes on a short-lived branch from `master` — `docs/...`, `chore/...`, `ci/...`, `feat/...` —
  and is merged **through a PR into `master`** after the user reviews it. The only automated PR is
  `bot/refresh-facts` (GitHub Actions).
- `oms-core`, `development`: `master` only.

### Rules for Claude and all agents

- **Never commit, push, merge or open a PR unless the user asked for it in this conversation.** Finishing a task means leaving changes uncommitted for the user to review in IntelliJ.
- When the user asks to commit: show `git status` / a short summary first, commit only the files of the task, one repo at a time.
- Never push to `develop` or `master` of any repo (services **and** `oms-workspace`), never force-push, never `reset --hard` or delete branches. Push only the working branch, then open a PR: **into `develop`** for services, **into `master`** for `oms-workspace`.
- Subagents (`*-expert`, `oms-architect`) are read-only analysts: they never run git write commands.
- `.claude/settings.json` enforces these with `ask`/`deny` rules; do not try to work around a blocked command — report it instead.

## Build & run

- Java 17, Spring Boot 3.2.3, Gradle. Each service `includeBuild('../oms-core')`, so **all repos must be siblings** — `repos/` keeps that layout.
- Infra: `cd repos/development/docker && docker compose up -d`, then Terraform in `repos/development/docker/infra/local`.
- Service: `./gradlew bootRun --args='--spring.profiles.active=localdev'`. Swagger at `/swagger-ui.html`.

## Keeping this map true

Two layers keep the docs aligned with code:

1. **Extracted facts** — `scripts/extract_facts.py` reads every service (`develop`) and writes
   `architecture/generated/`. The GitHub Action `refresh-facts.yml` runs it daily and opens a PR
   (label `architecture-drift`) when facts change. Never edit `architecture/generated/` by hand.
   When that PR shows changes, update the hand-written docs to match (or ask Claude:
   "update the docs to match architecture/generated").
2. **Same-PR rule** — when a change adds/changes a REST endpoint, event, table or aggregate, update
   `domain-map.md` and `integration.md` in the same piece of work. Service PRs touching those areas
   get an automatic reminder comment.

When hand-written docs and `architecture/generated/` disagree, **generated facts win** (they come from code).
Run `python3 scripts/extract_facts.py` locally after `sync-repos.sh` to refresh them.
