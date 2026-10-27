---
name: feature-impact
description: Analyse a new OMS feature or change across all services and produce a standard impact report (contexts, contracts, data, flow, consistency, rollout, risks). Use when the user asks to analyse, design or estimate a feature in the OMS.
---
# Feature impact analysis

Input: a feature description (from the user's message or `$ARGUMENTS`).

## Steps
1. Read `CLAUDE.md`, `architecture/vision.md`, `architecture/business-rules.md`, `architecture/domain-map.md`, `architecture/integration.md`, `architecture/open-questions.md` and the flows that relate to the feature. Cross-check endpoints, listeners, events and tables against `architecture/generated/` (extracted from code; it wins on conflict).
2. If more than one context may be affected, hand the work to the `oms-architect` agent; otherwise ask the single domain expert directly.
3. Verify every claim about existing behaviour in code under `repos/` — READMEs can be stale.
4. Write the report below. Ask the user about genuinely open business rules instead of inventing them.

## Report format

### 1. Summary & assumptions
What the feature does, in 2–3 sentences; list assumptions and open business questions. Cite the business rules used (`BR-…`) with their status; every 🟡/❓ rule is a question for the user, not an assumption.

### 2. Affected contexts
| Context | Why | Size (S/M/L) |

### 3. Contract changes
- REST: method, path, request/response — mark **BREAKING** where applicable; check *Front-end consumers* in `integration.md` (oms-web)
- Events: name, producer, consumers, payload (add JSON Schema to `architecture/contracts/events/`)

### 4. Data changes
Per service: Flyway migration (tables, columns, indexes, constraints), backfill needs.

### 5. End-to-end flow
Mermaid sequence diagram across services.

### 6. Consistency & failure handling
Transactions, outbox, idempotency key for each consumer, compensation per failure point, concurrency (oversell etc.).
Failure table per dependency: slow / down / partial → behaviour → recovery (`sa-resilience-observability`).

### 7. Volume & performance
Expected volumes (state which are estimates), bounded queries and jobs, indexes, whether N instances split or repeat the work, capacity limit (`sa-performance-scalability`).

### 8. Tenancy & security
How every new query is merchant-scoped, cross-merchant behaviour (404, nothing written), ids in request bodies, secrets/PII (`sa-multitenancy-security`).

### 9. Observability
Logs (ids, levels), metrics and the alert that would show this feature failing or falling behind.

### 10. Implementation plan per repo
Ordered list of files/classes to add or change, following hexagonal layout (domain → application → infrastructure → tests).

### 11. Test strategy
Tests per level and edge case, and how what unit tests cannot prove (SQL, transactions, JSON/validation, event compatibility) is verified (`sa-testing-strategy`).

### 12. Rollout order
Which repo ships first so nothing breaks (oms-core → producers of new events → consumers → API callers, including `oms-web`), feature flags if needed.

### 13. Risks & open questions
Including any item from `open-questions.md` the feature depends on. Anything deliberately deferred goes into `open-questions.md`.

### 14. Docs to update
`domain-map.md`, `integration.md`, flows, new ADR if a system rule changes.
