---
name: sa-analysis-checklist
description: Mandatory checklist for any OMS analysis, plan or review — evidence, runtime behaviour, concurrency, edge cases, tests, routing, and which other sa-* skill to open. Use before presenting a plan, analysis or review.
user-invocable: false
---
# Analysis checklist (solution-architect discipline)

Every analysis, plan or review you produce must pass this checklist **before** it is shown to the user.
If an item does not apply, say so in one line — do not silently skip it.

## 1. Evidence, not assumptions
- [ ] Every claim about current behaviour cites **`file:line`** (or a config key) you actually read.
- [ ] Claims about **runtime behaviour** (retries, transactions, ordering, defaults, what happens on exception)
      are verified in code/config. If behaviour comes from a framework default, name the default and say
      that no override exists (you searched for it). Never write "loops forever", "blocks", "is atomic"
      without that evidence.
- [ ] Facts come from `architecture/generated/` and code, not from READMEs. If docs disagree, code wins — note the drift.
- [ ] Unknown business rules are listed as **questions for the user**, not invented.
- [ ] A gap that sits in **another bounded context that this piece of work does not design or change** is recorded as
      an open question, with what this context guarantees for each choice the other side may make — never written
      into an ADR or flow as decided. How to record it: `.claude/skills/sa-analysis-checklist/references/cross-context-gaps.md`.

## 2. Root cause
- [ ] State the root cause in one sentence, then the **real impact** (data loss? duplicate? noise? stuck?).
- [ ] Distinguish *symptom* from *cause*.

## 3. Concurrency and failure
- [ ] Who can run this code **at the same time**? (two consumer instances, a rebalance, REST + consumer, a scheduled job + a request)
- [ ] What makes it safe? Name the mechanism: partition key ordering, unique constraint, conditional UPDATE, lock, idempotency key. "It's in a transaction" alone is not an answer.
- [ ] What happens on **redelivery / retry / crash halfway**? Is every step idempotent or compensated?
- See `sa-concurrency-consistency` and `sa-messaging-events`.

## 4. Edge cases (list them explicitly)
- [ ] empty input · duplicates inside the input · all items already exist · some exist · none exist
- [ ] data that exists but belongs to another merchant / product / store (mismatch) → 404, nothing written
- [ ] null / missing optional fields · very large batch
- [ ] a limit or rule taken from a (new) contract: does **every producer** of that input already enforce it, in deploy order? If not, the consumer rejects valid data during rollout — apply it only where the producer enforces it, and widen later
- [ ] invalid state transition (e.g. confirming an expired reservation)

## 5. Scale and operations
- [ ] Volume: how many rows/events/requests at peak and in a year? Fix the root problem for that volume, not only the reported symptom — or say explicitly what is deferred and add it to `open-questions.md`.
- [ ] Every query and loop bounded (page size, budget); index named; N instances split or duplicate the work? (`sa-performance-scalability`)
- [ ] Failure of each dependency: timeout, retry, DLQ, how we notice (metric/alert/log). (`sa-resilience-observability`)
- [ ] Merchant scoping of every lookup; no secrets/PII in logs. (`sa-multitenancy-security`)
- [ ] New endpoint: validation, status codes, idempotency, BREAKING? (`sa-api-design`) New AWS resource: Terraform, DLQ, naming. (`sa-aws-platform`)

## 6. Tests
- [ ] One test per edge case above, including **negative assertions** (`verify(x, never())`, "no row written").
- [ ] Say what is **not** covered by unit tests (e.g. native SQL, constraints, `@Transactional` boundaries, JSON/validation mapping) and how it is verified instead. (`sa-testing-strategy`)

## 7. Change surface and routing
Present a table — one row per file you will change:

| File | Repo | Branch | PR base |
|------|------|--------|---------|
| `src/.../CreateInventoryService.java` | inventory-service | `fix/<slug>` | `develop` |
| `CLAUDE.md` (service) | inventory-service | `fix/<slug>` (same branch) | `develop` |
| `architecture/open-questions.md` | oms-workspace | `docs/<slug>` | `master` |

- [ ] Contracts touched? REST / events / DB migration — mark **BREAKING** if consumers must change.
- [ ] Docs to update (`domain-map.md`, `integration.md`, flows, service `CLAUDE.md` Known gaps, `open-questions.md`).

## 8. Safety rules (never break)
- Never ask the user to paste tokens, passwords, keys or `gh auth token` output into the chat.
  If `gh` is not authenticated, ask the user to run `gh auth login`, or give the compare URL.
- Git and release rules: `CLAUDE.md` → *Rules for Claude and all agents*. Never edit `architecture/generated/` by hand.

## 9. Which other skill to open
Only this checklist is preloaded. Open the skills below for what the change touches — with the Skill tool, or by reading
`.claude/skills/<name>/SKILL.md`. Each has a `references/current-state.md` with how the OMS does it today.

| The change touches | Open |
|---|---|
| A REST endpoint or a service-to-service call | `sa-api-design`, `sa-multitenancy-security`, `sa-testing-strategy` |
| An event, a command, a consumer or the outbox | `sa-messaging-events`, `sa-resilience-observability`, `sa-testing-strategy` |
| SQL, a table, a migration, a transaction boundary | `sa-data-persistence`; add `sa-concurrency-consistency` when writes can overlap |
| Stock, quantities, a state machine, a multi-step flow | `sa-concurrency-consistency`, `sa-data-persistence` |
| A queue, bucket, schedule, Terraform, local infra | `sa-aws-platform`, `sa-resilience-observability` |
| An aggregate, a business rule, a type for oms-core | `sa-ddd-hexagonal` |
| A job, a batch, large volume | `sa-performance-scalability`, `sa-resilience-observability` |
| A new bounded context or service | `sa-ddd-hexagonal`, `sa-messaging-events`, `sa-multitenancy-security` |

Recurring cross-repo work has a step-by-step skill; follow it instead of working the order out again: `change-event`
(a message), `change-api` (an endpoint), `add-migration` (a schema change), `add-aws-resource`, `new-service`.
