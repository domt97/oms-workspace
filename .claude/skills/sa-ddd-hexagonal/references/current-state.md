# DDD & hexagonal architecture — how the OMS does it today (snapshot)

Moved out of `SKILL.md` so the rules load without it. This is a hand-written snapshot, not a rule: before relying on
a line, check it against `architecture/generated/<service>.md` and the code — code wins. A gap listed here without an
open-question number is not yet in `architecture/open-questions.md`.

## OMS today
- **One bounded context per repo**: Store (`stores-service`), Inventory (`inventory-service`); Order and Promotion are planned. Each owns its own Postgres database — no cross-DB reads (workspace `CLAUDE.md`, rule 1).
- **Layers** in every service (`com.dotran.oms.<context>`):
  - `domain/` — pure Java: `model`, `valueobject`, `enums`, `event`, `exception`. No Spring, JPA or Kafka; Lombok (`@Builder`, `@Getter`) is the accepted exception.
  - `application/` — `usecase/` (inbound ports, `XxxUseCase`), `service/` (`@UseCase` impl, `@Transactional`), `repository/` and `client/` (outbound ports), `command/` (`XxxCmd`), `dto/`, `mapper/`.
  - `infrastructure/` — `rest/` (`@WebAdapter`, Request/Response, exception handler), `persistence/` (`@PersistenceAdapter`, JPA entities, `SpringDataXxxRepository`), `message/` (consumers + external DTOs = ACL).
- **Shared kernel** `oms-core`: typed IDs extending `BaseId<T>` (value equality via `equals`/`hashCode`, `oms-core/.../domain/id/BaseId.java`), `AggregateRoot` (marker class, `oms-core/.../domain/AggregateRoot.java`), `Money`, `Address`, exceptions (`BusinessException`, `NotFoundException`, `ValidationException`) mapped in `GlobalExceptionHandler`, stereotype annotations.
- **ACL**: external event payloads live in `infrastructure/message/dto` and are mapped to commands; e.g. inventory's `ProductCreatedEvent` DTO is a copy of the stores domain event, not shared code.

## Known gaps
- `AggregateRoot` is only a marker; aggregates do not collect domain events — integration events are built in the application layer (`OutboxEventHelper`).
- Order context does not exist yet; `OrderId`/`OrderItemId` already live in `oms-core`.
- `oms-core/.../domain/page/PagedResult.java` imports Spring Data `Page` — the only framework dependency inside a `domain` package.
