---
name: sa-ddd-hexagonal
description: Domain-Driven Design and hexagonal architecture as applied in the OMS — bounded contexts, aggregates and invariants, ports and adapters, anti-corruption layer, shared kernel (oms-core). Use when deciding where code or a rule belongs, designing a new aggregate/use case, or reviewing layering.
---
# DDD & hexagonal architecture

## OMS today
- **One bounded context per repo**: Store (`stores-service`), Inventory (`inventory-service`); Order and Promotion are planned. Each owns its own Postgres database — no cross-DB reads (workspace `CLAUDE.md`, rule 1).
- **Layers** in every service (`com.dotran.oms.<context>`):
  - `domain/` — pure Java: `model`, `valueobject`, `enums`, `event`, `exception`. No Spring, JPA or Kafka; Lombok (`@Builder`, `@Getter`) is the accepted exception.
  - `application/` — `usecase/` (inbound ports, `XxxUseCase`), `service/` (`@UseCase` impl, `@Transactional`), `repository/` and `client/` (outbound ports), `command/` (`XxxCmd`), `dto/`, `mapper/`.
  - `infrastructure/` — `rest/` (`@WebAdapter`, Request/Response, exception handler), `persistence/` (`@PersistenceAdapter`, JPA entities, `SpringDataXxxRepository`), `message/` (consumers + external DTOs = ACL).
- **Shared kernel** `oms-core`: typed IDs extending `BaseId<T>` (value equality via `equals`/`hashCode`, `oms-core/.../domain/id/BaseId.java`), `AggregateRoot` (marker class, `oms-core/.../domain/AggregateRoot.java`), `Money`, `Address`, exceptions (`BusinessException`, `NotFoundException`, `ValidationException`) mapped in `GlobalExceptionHandler`, stereotype annotations.
- **ACL**: external event payloads live in `infrastructure/message/dto` and are mapped to commands; e.g. inventory's `ProductCreatedEvent` DTO is a copy of the stores domain event, not shared code.

## Rules
1. **Invariants live in the aggregate.** A rule that must always hold (`available = quantity − reserved ≥ 0`, "only RESERVED can be confirmed") is enforced by an aggregate method that throws a domain exception. Services orchestrate; they do not re-implement rules.
2. **Aggregate = consistency boundary.** One transaction changes one aggregate instance. If a use case must change two aggregates atomically, question the boundary first; otherwise use a guarded DB statement or an event + eventual consistency.
3. **Reference other aggregates by typed ID only** (`InventoryId`, `ProductId`), never by object reference — especially across contexts.
4. **Ports belong to the application layer**; adapters implement them in infrastructure. The domain never imports Spring, JPA, Kafka or AWS.
5. **Cross-context data is a copy, not a join.** If inventory needs product data, it keeps what it needs from events (`ProductCreated`) or asks via a client port — never reads the store DB.
6. **ACL for every inbound integration.** External DTO → command at the edge; domain types never depend on another context's schema.
7. **Shared kernel is small.** Put something in `oms-core` only if ≥2 contexts need *the same meaning*. A type that merely looks similar stays in each context. Changes to `oms-core` force every service to rebuild — treat them as contract changes.
8. **Use cases are verbs of the business** (`ReserveStock`, `CloseStore`), not CRUD on tables.

## Checklist
- [ ] Which aggregate owns the rule? Is it enforced inside the aggregate (domain test proves it)?
- [ ] Does the change touch more than one aggregate in one transaction? Why is that acceptable?
- [ ] Does any domain class gain a framework import? (must not)
- [ ] Is a new cross-context dependency an event (preferred) or a sync client? Is there an ACL DTO?
- [ ] Does anything new belong in `oms-core`? Justify with ≥2 consumers of the same meaning.

## Anti-patterns to flag
- Business rules in controllers, mappers, or JPA entities.
- Domain model mutated through setters from services (use intention-revealing methods).
- Re-using another context's domain class instead of an ACL DTO.
- "Anemic" aggregates whose invariants are only checked in SQL — SQL guards are the concurrency backstop (see `sa-concurrency-consistency`), the aggregate method is still the source of the rule.

## Known gaps
- `AggregateRoot` is only a marker; aggregates do not collect domain events — integration events are built in the application layer (`OutboxEventHelper`).
- Order context does not exist yet; `OrderId`/`OrderItemId` already live in `oms-core`.
- `oms-core/.../domain/page/PagedResult.java` imports Spring Data `Page` — the only framework dependency inside a `domain` package.
