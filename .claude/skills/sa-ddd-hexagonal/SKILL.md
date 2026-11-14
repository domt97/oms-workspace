---
name: sa-ddd-hexagonal
description: DDD and hexagonal rules — bounded contexts, aggregates, ports and adapters, anti-corruption layer, what belongs in oms-core. Use when deciding where code or a rule belongs, or designing an aggregate or use case.
user-invocable: false
---
# DDD & hexagonal architecture

## Rules
1. **Invariants live in the aggregate.** A rule that must always hold (`available = quantity − reserved ≥ 0`, "only RESERVED can be confirmed") is enforced by an aggregate method that throws a domain exception. Services orchestrate; they do not re-implement rules.
   - A rule about one **child entity** (e.g. a SKU's currency and price inside `StoreProduct`) is a method on that child, and the aggregate calls it on **every path that creates or changes the child**: the factory/`init`, `addX`, and any replace/update method. A rule placed only in the creation step is bypassed by the other paths (stores-service: `ProductSku.normaliseForSale()` runs from `StoreProduct.initState()` and `addSku()`).
2. **Aggregate = consistency boundary.** One transaction changes one aggregate instance. If a use case must change two aggregates atomically, question the boundary first; otherwise use a guarded DB statement or an event + eventual consistency.
3. **Reference other aggregates by typed ID only** (`InventoryId`, `ProductId`), never by object reference — especially across contexts.
4. **Ports belong to the application layer**; adapters implement them in infrastructure. The domain never imports Spring, JPA, Kafka or AWS.
5. **Cross-context data is a copy, not a join.** If inventory needs product data, it keeps what it needs from events (`ProductCreated`) or asks via a client port — never reads the store DB.
6. **ACL for every inbound integration.** External DTO → command at the edge; domain types never depend on another context's schema.
7. **Shared kernel is small.** Put something in `oms-core` only if ≥2 contexts need *the same meaning*. A type that merely looks similar stays in each context. Changes to `oms-core` are contract changes: they reach a service only when it bumps `coreVersion` (ADR 0005), and a breaking change is a MAJOR release.
8. **Use cases are verbs of the business** (`ReserveStock`, `CloseStore`), not CRUD on tables.

## Checklist
- [ ] Which aggregate owns the rule? Is it enforced inside the aggregate (domain test proves it)?
- [ ] Rule on a child entity: list every aggregate method that creates or changes that child, and show each one applies the rule (one test per path).
- [ ] Does the change touch more than one aggregate in one transaction? Why is that acceptable?
- [ ] Does any domain class gain a framework import? (must not)
- [ ] Is a new cross-context dependency an event (preferred) or a sync client? Is there an ACL DTO?
- [ ] Does anything new belong in `oms-core`? Justify with ≥2 consumers of the same meaning.

## Anti-patterns to flag
- Business rules in controllers, mappers, or JPA entities.
- Domain model mutated through setters from services (use intention-revealing methods).
- Re-using another context's domain class instead of an ACL DTO.
- "Anemic" aggregates whose invariants are only checked in SQL — SQL guards are the concurrency backstop (see `sa-concurrency-consistency`), the aggregate method is still the source of the rule.

## Current state and known gaps
Not in this file. When you need how the OMS does this today, or which gaps are known, read
`.claude/skills/sa-ddd-hexagonal/references/current-state.md`. It is a snapshot: `architecture/generated/` and the code win.
