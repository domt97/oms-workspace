# OMS Workspace — System Map

Multi-merchant marketplace **Order Management System** launching in Vietnam (VND) and not limited to one market or currency (BR-MER-01): **merchants** (sellers, often chains) run **stores**; customers are platform users who buy across merchants. Each bounded context lives in its own GitHub repo;
this workspace holds the cross-repo knowledge (architecture, contracts, flows) and clones every
repo into `repos/` so Claude can reason about the whole system.

> First time / repos missing? Run `./scripts/sync-repos.sh`.

## Repositories

| Repo | Path | Role | Port |
|------|------|------|------|
| `stores-service` | `repos/stores-service` | Store bounded context: merchants (seller self-registration), stores, own products (SKU, images), collections, business hours, availability. Publishes `ProductCreated` and `ProductUpdated` via outbox. | 8048 |
| `inventory-service` | `repos/inventory-service` | Inventory bounded context: stock per (store, SKU), reservations, stock movement audit. | 8058 |
| `oms-core` | `repos/oms-core` | Shared kernel, published to GitHub Packages by version (services pin `coreVersion`; composite build locally, ADR 0005): typed IDs, `AggregateRoot`, `Money`/`Address`, exceptions, `@UseCase`/`@WebAdapter`/`@PersistenceAdapter`, S3, Excel import template. | – |
| `development` | `repos/development` | Local infra: docker-compose (Kafka, Kafka Connect + Debezium, Schema Registry, Postgres 16, Redis, LocalStack) and Terraform for LocalStack (S3, SQS, EventBridge). | – |
| `oms-web` | `repos/oms-web` | Front end (React 19 + TypeScript, Vite): shopper storefront at `/` and Seller Centre at `/seller`. Calls stores-service and inventory-service through a proxy on `/v1/store/` and `/v1/inventory/`; cart, orders and sign-in are browser-local stand-ins until those services exist. Architecture in `docs/architecture.md`. | 5173 (dev) |

Not built yet but referenced in code: **order-service** (will send the stock commands of ADR 0006; inventory already consumes them), **promotion-service** (`PromotionServiceClient`).

## Where to look

| Need | File |
|------|------|
| Product vision, subdomains, bounded contexts (built + planned), context map, roadmap | `architecture/vision.md` |
| Business rules (✅ in code / 🟢 decided / 🟡 proposed / ❓ open) and open business questions | `architecture/business-rules.md` |
| Big picture, tech stack, conventions | `architecture/system-overview.md` |
| Who owns what (entities, tables, APIs, events) | `architecture/domain-map.md` |
| Every event and REST endpoint between services | `architecture/integration.md` |
| End-to-end flows | `architecture/flows/*.md` |
| Why things are the way they are | `architecture/adr/*.md` |
| Terms (SKU, reservation, movement…) | `architecture/glossary.md` |
| **Extracted facts (generated from code, ground truth)** | `architecture/generated/<service>.md`, `facts.json` |
| Known gaps and doc/code drift | `architecture/open-questions.md` |
| How to work inside one service (layout, checklist, invariants) | `repos/<service>/CLAUDE.md` |
| Front-end layers, dependency rule, which backend endpoints the web uses and its temporary stand-ins | `repos/oms-web/docs/architecture.md`, `integration.md` → *Front-end consumers* |
| Solution-architect rules by concern, and which one to open for a change | `.claude/skills/sa-*/SKILL.md`; routing table in `sa-analysis-checklist` §9 |
| Branch model, build and run, CI, oms-core releases | `architecture/delivery.md` |

## System rules (do not violate when designing features)

1. **Database per service.** stores → Postgres DB `store`, inventory → DB `inventory`. Never query or join across.
2. **Cross-service writes go through events**, published with the **transactional outbox + Debezium CDC** (`outbox_events` table). Never publish to Kafka directly from a use case.
3. **Hexagonal / DDD in every service**: `domain` (pure Java) ← `application` (use cases, ports) ← `infrastructure` (adapters). External event DTOs live in `infrastructure/message/dto` (anti-corruption layer) and are mapped to commands.
4. **Merchant isolation**: every merchant-owned aggregate root (store, catalog, inventory, order) belongs to exactly one merchant — directly (`merchant_id`) or through an immutable parent (`store_id` → store → merchant). Customer-owned data (customer, cart, checkout, payment) belongs to the platform and is scoped by `customer_id`. Every query filters by merchant (or a merchant-checked parent) or by customer — never by id alone. Merchants live in stores-service (Postgres table `merchants`); other services only carry `merchant_id`.
5. **Aggregates reference each other by typed ID only** (`StoreId`, `ProductId`, `SKU`… from `oms-core`).
6. Shared types go to `oms-core` only if they are truly cross-context; otherwise keep them in the owning service.
7. Consumers must be **idempotent** (Debezium gives at-least-once delivery).
8. **Kafka topic name = message type** (event `ProductCreated`, command `ReserveStock`), key = aggregate id. Names are unique across services (ADR 0002). Commands between services also go through the sender's outbox, and replies through the executor's outbox (ADR 0006).

## How to work

- **Analyse a feature or change:** `/feature-impact`. It decides which contexts are affected, hands multi-context work to
  the `oms-architect` agent (which asks `store-expert`, `inventory-expert`, `platform-expert`, `web-expert`) and writes the standard report.
  Start from the map, not the code: `system-overview.md`, `domain-map.md`, then only the rules, integration sections and
  flow the feature touches. In a service, read `repos/<service>/CLAUDE.md` first, then `application/usecase` and `domain/model`.
- **Business rules:** design only on ✅ (in code) and 🟢 (decided) rules, or on ones the user confirmed in this conversation.
  For 🟡/❓ rules **ask the user** (quote the id) — never invent a business rule.
- **Implement in a service:** the user runs `/ship <service> <feature|fix> <slug>` (it does not start by itself): branch
  from `develop`, plan with the domain expert, user approves, implement, test, review, docs, then — after asking — commit,
  push and a PR **into `develop`**. Several services: `/feature-impact` first, then one `/ship` per service. `oms-web`: same
  steps by hand, `npm run check` instead of `./gradlew test`, keep the layer rule in its `docs/architecture.md`.
- A backend change to an endpoint listed under *Front-end consumers* in `integration.md` (path, auth, paging cap, response
  fields) is a breaking change for oms-web: include oms-web in the analysis and the rollout order.
- **Recurring cross-repo work** has step-by-step skills: `change-event`, `change-api`, `add-migration`, `add-aws-resource`,
  `new-service`. Releasing oms-core: the user runs `/release-core`. Docs drifted from code: `docs-sync`.
- Docs in service READMEs may be out of date; **code wins**. Known gaps: `open-questions.md`.

## Review policy

How much review a piece of work gets depends on what it changes. Whoever presents the work to the user runs it (the main
session, or `oms-architect`; the domain experts cannot call agents).

| Level | Applies to | Review |
|-------|------------|--------|
| 0 | Typos, links, formatting; regenerated `architecture/generated/`; a doc edit that changes no rule, contract, ADR or permission | Self-check against `sa-analysis-checklist`. No reviewer. |
| 1 | Workspace docs, skills or agents that change a statement about the system | `docs-reviewer`, one round. |
| 2 | Plans, root-cause analyses, code diffs, and any change to a contract, a business rule, an ADR or `.claude/settings.json` | `plan-reviewer`. A follow-up round gets the previous Must fix list verbatim, how each was fixed and the changed files/lines, and reviews only what changed. |

- Level 2 stops after **2 rounds**: show the user the Must fix items still open and the last verdict; the user decides.
  Stop earlier when a Must fix needs the user's decision (a 🟡/❓ rule) or a finding comes back after being fixed.
- An edit made after a clean round is reviewed again only if the edit itself is level 1 or 2.
- Never present work as clean that has not passed its last round. Always tell the user the level used and the last verdict.
  The user may waive a review; say so in the PR.

## Git rules

Branch model, build, CI and releases: `architecture/delivery.md`. In short: services and `oms-web` branch from and merge
into `develop`; `oms-workspace` changes go on `docs/…`, `chore/…`, `ci/…` or `feat/…` branches and merge through a PR into
`master`; `oms-core` and `development` have `master` only.

### Rules for Claude and all agents

- **Never commit, push, merge or open a PR unless the user asked for it in this conversation.** Finishing a task means leaving changes uncommitted for the user to review in IntelliJ.
- When the user asks to commit: show `git status` / a short summary first, commit only the files of the task, one repo at a time.
- Never push to `develop` or `master` of any repo (services, `oms-web` **and** `oms-workspace`), never force-push, never `reset --hard` or delete branches. Push only the working branch, then open a PR: **into `develop`** for services and `oms-web`, **into `master`** for `oms-workspace`.
- **Only the user creates rc tags** (`git tag`, `gh release`), and only the user merges oms-core PRs: a merge with a bumped
  `version` publishes an oms-core version that can never be changed. Claude may bump `version` in a PR when asked and must
  say in the PR what merging will release.
- Subagents (`*-expert`, `oms-architect`) are read-only analysts: they never run git write commands.
- `.claude/settings.json` backs these rules up twice. Its `ask`/`deny` rules match the usual spellings. The hook
  `.claude/hooks/guard_git.py` parses each Bash command, also behind `git -C …` or `cd … &&`, and blocks: a push to
  `master`/`develop`, force, delete and tag pushes, `reset --hard`, deleting a branch or tag, creating a tag or release,
  merging an oms-core PR. It reads the command line only (not scripts, aliases or unknown variables), so these rules hold
  whether or not something blocks. Do not try to work around a blocked command — report it instead.

## Keeping this map true

- `scripts/extract_facts.py` reads every service (`develop`) and writes `architecture/generated/`; `refresh-facts.yml` runs it
  daily and opens a PR (label `architecture-drift`) when facts change. When hand-written docs and generated facts
  disagree, **generated facts win**. Run `python3 scripts/extract_facts.py` after `sync-repos.sh` to refresh them locally.
- How to write and update the docs (same-PR rule, contract check, never edit generated files): `.claude/rules/architecture-docs.md`.
  Skills and agents: `.claude/rules/agents-skills.md`.
