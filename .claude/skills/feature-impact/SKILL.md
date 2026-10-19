---
name: feature-impact
description: Analyse a new OMS feature or change across all services and produce a standard impact report (contexts, contracts, data, flow, consistency, rollout, risks). Use when the user asks to analyse, design or estimate a feature in the OMS.
---
# Feature impact analysis

Input: a feature description (from the user's message or `$ARGUMENTS`).

## Steps
1. Read `CLAUDE.md`, `architecture/domain-map.md`, `architecture/integration.md`, `architecture/open-questions.md` and the flows that relate to the feature. Cross-check endpoints, listeners, events and tables against `architecture/generated/` (extracted from code; it wins on conflict).
2. If more than one context may be affected, hand the work to the `oms-architect` agent; otherwise ask the single domain expert directly.
3. Verify every claim about existing behaviour in code under `repos/` — READMEs can be stale.
4. Write the report below. Ask the user about genuinely open business rules instead of inventing them.

## Report format

### 1. Summary & assumptions
What the feature does, in 2–3 sentences; list assumptions and open business questions.

### 2. Affected contexts
| Context | Why | Size (S/M/L) |

### 3. Contract changes
- REST: method, path, request/response — mark **BREAKING** where applicable
- Events: name, producer, consumers, payload (add JSON Schema to `architecture/contracts/events/`)

### 4. Data changes
Per service: Flyway migration (tables, columns, indexes, constraints), backfill needs.

### 5. End-to-end flow
Mermaid sequence diagram across services.

### 6. Consistency & failure handling
Transactions, outbox, idempotency key for each consumer, compensation per failure point, concurrency (oversell etc.).

### 7. Implementation plan per repo
Ordered list of files/classes to add or change, following hexagonal layout (domain → application → infrastructure → tests).

### 8. Rollout order
Which repo ships first so nothing breaks (oms-core → producers of new events → consumers → API callers), feature flags if needed.

### 9. Risks & open questions
Including any item from `open-questions.md` the feature depends on.

### 10. Docs to update
`domain-map.md`, `integration.md`, flows, new ADR if a system rule changes.
