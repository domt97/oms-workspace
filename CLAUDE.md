# OMS Workspace — System Map

Multi-merchant marketplace **Order Management System** launching in Vietnam (VND) and not limited to one market or currency (BR-MER-01): **merchants** (sellers, often chains) run **stores**; customers are platform users who buy across merchants. Each bounded context lives in its own GitHub repo;
this workspace holds the cross-repo knowledge (architecture, contracts, flows) and clones every
repo into `repos/` so Claude can reason about the whole system.

> First time / repos missing? Run `./scripts/sync-repos.sh`.

## Repositories

| Repo | Path | Role | Port |
|------|------|------|------|
| `stores-service` | `repos/stores-service` | Store bounded context: merchants (seller self-registration), stores, own products (SKU, images), collections, business hours, availability. Publishes `ProductCreated` via outbox. | 8048 |
| `inventory-service` | `repos/inventory-service` | Inventory bounded context: stock per (store, SKU), reservations, stock movement audit. | 8058 |
| `oms-core` | `repos/oms-core` | Shared kernel, published to GitHub Packages by version (services pin `coreVersion`; composite build locally, ADR 0005): typed IDs, `AggregateRoot`, `Money`/`Address`, exceptions, `@UseCase`/`@WebAdapter`/`@PersistenceAdapter`, S3, Excel import template. | – |
| `development` | `repos/development` | Local infra: docker-compose (Kafka, Kafka Connect + Debezium, Schema Registry, Postgres 16, Redis, LocalStack) and Terraform for LocalStack (S3, SQS, EventBridge). | – |
| `oms-web` | `repos/oms-web` | Front end (React 19 + TypeScript, Vite): shopper storefront at `/` and Seller Centre at `/seller`. Calls stores-service and inventory-service through a proxy on `/v1/store/` and `/v1/inventory/`; cart, orders and sign-in are browser-local stand-ins until those services exist. Architecture in `docs/architecture.md`. | 5173 (dev) |

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
| Front-end layers, dependency rule, which backend endpoints the web uses and its temporary stand-ins | `repos/oms-web/docs/architecture.md`, `integration.md` → *Front-end consumers* |
| Solution-architect knowledge (DDD, messaging, data, concurrency, performance/scale, API design, multi-tenancy/security, resilience/observability, testing, AWS platform, analysis checklist) | `.claude/skills/sa-*/SKILL.md` |

## System rules (do not violate when designing features)

1. **Database per service.** stores → Postgres DB `store`, inventory → DB `inventory`. Never query or join across.
2. **Cross-service writes go through events**, published with the **transactional outbox + Debezium CDC** (`outbox_events` table). Never publish to Kafka directly from a use case.
3. **Hexagonal / DDD in every service**: `domain` (pure Java) ← `application` (use cases, ports) ← `infrastructure` (adapters). External event DTOs live in `infrastructure/message/dto` (anti-corruption layer) and are mapped to commands.
4. **Merchant isolation**: every merchant-owned aggregate root (store, catalog, inventory, order) belongs to exactly one merchant — directly (`merchant_id`) or through an immutable parent (`store_id` → store → merchant). Customer-owned data (customer, cart, checkout, payment) belongs to the platform and is scoped by `customer_id`. Every query filters by merchant (or a merchant-checked parent) or by customer — never by id alone. Merchants live in stores-service (Postgres table `merchants`); other services only carry `merchant_id`.
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
6. Every analysis, plan or diff (code or docs) must pass `sa-analysis-checklist` and be challenged by the `plan-reviewer`
   agent before it is presented, committed or put in a PR. **Review until clean** — run by whoever presents the work to
   the user (the main session, or `oms-architect`; domain experts cannot call agents):
   - after fixing the findings, send `plan-reviewer` the **previous round's Must fix list verbatim**, how each was fixed,
     and the changed files/lines (a new reviewer remembers nothing). A follow-up round reviews **only what changed since
     the previous round** — each fix, and the places that depend on it (callers, other files, docs, contracts, tests) —
     not the whole work again;
   - repeat until a round has an **empty Must fix list** (that is "clean", whatever the verdict word); any later edit,
     even a small one, gets its own round;
   - **stop and ask the user** after 3 rounds (a new piece of work, e.g. a plan change the user asked for or a CI fix,
     starts again at round 1), or earlier when a Must fix needs the user's decision (e.g. a 🟡/❓ rule),
     a finding comes back after being fixed, or the reviewer contradicts an earlier round. Show the open Must fix items,
     the last verdict and the number of rounds; the user decides;
   - never present a version **as clean** that has not passed the last round, and commit or open a PR only when it is
     clean or the user has seen the open findings and still asks for it. Always tell the user the last round's verdict.

## How to implement a change

Use the `/ship <service> <feature|fix> <slug>` skill for any implementation in a service: it branches
from `develop`, plans with the domain expert (user approves), implements, runs `./gradlew test`,
reviews, updates docs, and — after asking — commits, pushes and opens a PR **into `develop`**.
For changes spanning several services, run `/feature-impact` first, then one `/ship` per service.
`/ship` targets the Gradle services; for `oms-web` follow the same steps by hand (branch from `develop`,
keep the layer rule in `docs/architecture.md`, run `npm run check` instead of `./gradlew test`, PR into `develop`).
A backend change to an endpoint listed under *Front-end consumers* in `integration.md` (path, auth, paging cap,
response fields) is a breaking change for oms-web: include oms-web in the impact analysis and rollout order.

## Git workflow

- Service repos (`stores-service`, `inventory-service`) and `oms-web`: `master` is the release branch; **`develop`** is the
  integration branch and the GitHub default branch (new PRs and clones target `develop`).
  Branch features/fixes **from `develop`** and open PRs **into `develop`**; `master` only receives `develop` via release PRs.
- `oms-workspace`: `master` is protected. Every change (docs, agents, skills, scripts, workflows)
  goes on a short-lived branch from `master` — `docs/...`, `chore/...`, `ci/...`, `feat/...` —
  and is merged **through a PR into `master`** after the user reviews it. The only automated PR is
  `bot/refresh-facts` (GitHub Actions).
- `oms-core`, `development`: `master` only. oms-core is released continuously: the `version` in its `gradle.properties`
  is published to GitHub Packages and tagged `vX.Y.Z` by `publish.yml` when it reaches `master` (bump it in the PR to
  release); pre-releases are `vX.Y.Z-rc.N` tags on a branch (`release.yml`). See oms-core `README.md`.

### Rules for Claude and all agents

- **Never commit, push, merge or open a PR unless the user asked for it in this conversation.** Finishing a task means leaving changes uncommitted for the user to review in IntelliJ.
- When the user asks to commit: show `git status` / a short summary first, commit only the files of the task, one repo at a time.
- Never push to `develop` or `master` of any repo (services, `oms-web` **and** `oms-workspace`), never force-push, never `reset --hard` or delete branches. Push only the working branch, then open a PR: **into `develop`** for services and `oms-web`, **into `master`** for `oms-workspace`.
- **Only the user creates rc tags** (`git tag`, `gh release`), and only the user merges oms-core PRs: a merge with a bumped
  `version` publishes an oms-core version that can never be changed. Claude may bump `version` in a PR when asked and must
  say in the PR what merging will release.
- Subagents (`*-expert`, `oms-architect`) are read-only analysts: they never run git write commands.
- `.claude/settings.json` enforces these with `ask`/`deny` rules; do not try to work around a blocked command — report it instead.

## Build & run

- Java 17, Spring Boot 3.2.3, Gradle. Locally each service uses `../oms-core` as a composite build when it exists (`repos/`
  keeps the repos as siblings; the build log says so) and then ignores `coreVersion`. CI and releases have no sibling: they
  download the pinned `coreVersion` from GitHub Packages (ADR 0005). Building a service without `../oms-core` needs
  `gpr.user`/`gpr.key` (classic token, `read:packages`) in `~/.gradle/gradle.properties`.
- Infra: `cd repos/development/docker && docker compose up -d`, then Terraform in `repos/development/docker/infra/local`.
- Service: `./gradlew bootRun --args='--spring.profiles.active=localdev'`. Swagger at `/swagger-ui.html`.
- Web: Node 20.19+ or 22.12+; in `repos/oms-web` run `npm install`, then `npm run dev` → http://localhost:5173
  (Seller Centre `/seller`). It proxies to the services on 8048 / 8058. `npm run check` = typecheck + layer rule + tests.

## CI (GitHub Actions, `.github/workflows/ci.yml` in each code repo)

- **stores-service, inventory-service:** `./gradlew test` on every PR and push to `develop`/`master`, against the **pinned
  `coreVersion`** from GitHub Packages (no oms-core checkout; `GITHUB_TOKEN` with `packages: read`). Job **`core-pin`** fails
  while `coreVersion` is a pre-release (`-rc.N`). Test reports are uploaded as an artifact on failure.
- **oms-core:** its own tests plus a dry run of the publication files (POM, Gradle module metadata); on PRs, `release-version`
  says what merging will release. **CD:** `publish.yml` on every push to `master` publishes `gradle.properties` `version`
  if it is new (tests first) and tags `vX.Y.Z`; `release.yml` publishes rc tags. Versions are immutable.
- **oms-web:** `npm run build` (typecheck, layer rule, tests, Vite build) on Node 22.
- **A service picks up an oms-core change only when it bumps `coreVersion`.** Cross-repo change:
  1. change oms-core and the service together locally (composite build);
  2. optional, for CI feedback before oms-core is merged: the user tags the oms-core branch `vX.Y.Z-rc.N`, the service PR pins
     it (`test` green, `core-pin` red: not mergeable);
  3. merge oms-core with `version=X.Y.Z` bumped; wait for the **Publish** run (it tags `vX.Y.Z`);
  4. the service PR sets `coreVersion=X.Y.Z` (no `v`; `core-pin` green) and is merged.
  A service PR whose pinned version is not published yet has a red `test`: never merge it before the Publish run is green.
  Breaking change in oms-core = MAJOR version (oms-core `README.md`).
- Unit tests only (no Docker); SQL, Debezium and Kafka behaviour stay manual checks.
- Branch protection (after the first green runs): required checks `Unit tests` and `core-pin` on service `develop`/`master`,
  `oms-core unit tests` and `release-version` on oms-core `master`, `Check and build` on oms-web.

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
