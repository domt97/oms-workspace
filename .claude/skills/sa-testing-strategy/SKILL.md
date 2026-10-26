---
name: sa-testing-strategy
description: Testing strategy in the OMS — what each test level proves (domain, service, adapter, controller, SQL/integration, contract), what Mockito-only tests cannot catch, how to verify native SQL, transactions, constraints and message handling, and what to require in a plan's test list. Use when planning tests for a change, reviewing a diff's tests, or deciding how to verify behaviour unit tests do not cover.
---
# Testing strategy

## OMS today (verified in code)
**Test suites**
- Both services use JUnit 5 + Mockito only (`@ExtendWith(MockitoExtension.class)`, `@Mock`/`@InjectMocks`, `@DisplayName`), plus AssertJ from `spring-boot-starter-test`. There is no Spring context, no database and no broker.
  - stores-service: 37 test classes (service 17, domain 6, persistence 6, rest 5, event, impex, excel).
  - inventory-service: 23 test classes (service 8, domain 4, rest 4, message 3, persistence 3, config 1).
- **Controller tests call the controller method directly** (e.g. `StoreCollectionControllerTest`, `controller.create(...)`). They do **not** exercise URL mapping, JSON (de)serialisation, `@Valid` constraints, status codes or `GlobalExceptionHandler` mapping.
- Persistence adapter tests mock the Spring Data repository. **Native SQL, JPQL, constraints, indexes, Flyway migrations and `@Transactional` boundaries are not exercised by any test.**
- `@ConfigurationProperties` validation is tested with a plain `jakarta.validation.Validator` (`ReservationExpiryPropertiesTest`).

**No Testcontainers and no CI**
- No Testcontainers dependency.
- **No CI runs the tests.** Service workflows are only `architecture-reminder.yml` and `delete-merged-branches.yml`, so `./gradlew test` runs only locally (the `/ship` gate).

**Runtime checks done instead**
- Changes to SQL have been checked by hand against local Postgres (EXPLAIN, run against seeded data), as in inventory-service#27 and #28.

## Rules
1. **Test what can break, at the cheapest level that can catch it.**

   | Level | Proves | Misses |
   |-------|--------|--------|
   | Domain (pure JUnit) | invariants, state transitions, value objects | wiring, SQL |
   | Service (Mockito) | orchestration: what is loaded/saved/published, branches, exceptions; negative assertions `verify(x, never())` | real SQL, transactions, rollbacks |
   | Controller slice (`@WebMvcTest` + MockMvc) | path, JSON, validation → 400, exception → status, response shape | business logic |
   | Repository/SQL (`@DataJpaTest` or Testcontainers Postgres + Flyway) | native queries, guards (row counts), constraints, index use, migration applies | concurrency under load |
   | Messaging (Testcontainers Kafka / LocalStack, or the listener method + error handler config) | deserialisation, idempotency on redelivery, DLQ routing | — |
   | Contract | event payload matches `architecture/contracts/events/*.schema.json` on both producer and consumer | — |

2. **Mocks lie about SQL.** Any change to a native query, a guard `WHERE`, a constraint, a migration or a transaction boundary needs one of:
   - (a) a Testcontainers/`@DataJpaTest` test; or
   - (b) a documented manual check against local Postgres (statement, data, result, EXPLAIN) in the PR description.

   Prefer (a) once the dependency is added.
3. **Transactions are not tested by Mockito.** `@Transactional` on a self-invoked or non-public method is ignored at runtime; a mock-based test passes anyway. Verify boundaries by reading the call path (proxy entry point), or with an integration test that forces a failure after the first write and asserts nothing was committed.
4. **Concurrency claims need a concurrency test or a proof.** Either run two transactions against real Postgres (two threads, a latch), or write the interleaving argument in the plan (guard + row count). Never "it's in a transaction".
5. **Every edge case in the plan has a test**, including negative assertions:
   - "no row written", "no event", "never called";
   - duplicates in input;
   - wrong merchant/store;
   - redelivered message.
6. **Event contracts**: when changing `ProductCreatedEvent` (duplicated in two repos), test serialisation on the producer and deserialisation of an **old** payload on the consumer (backward compatibility).
7. **Test data** via aggregate builders and fixtures; fix the clock (`Clock` bean, `Clock.fixed`) for time-based logic.
8. **Keep tests fast and deterministic**: no sleeps (use latches or Awaitility with a timeout), no random ports or real AWS, no order dependence.

## Checklist
- [ ] Test list per level, one per edge case, with negative assertions.
- [ ] What unit tests cannot prove here (SQL, constraint, transaction, serialisation, concurrency) and how it is verified instead.
- [ ] Redelivery/idempotency test for consumers; cross-merchant test for lookups.
- [ ] Old-payload compatibility test if an event changed.
- [ ] `./gradlew test` result in the PR; manual verification steps written down if any.

## Known gaps
- No integration tests (DB, Kafka, SQS, S3); no Testcontainers; no MockMvc controller tests.
- No CI pipeline running tests or build on PRs.
- No contract tests for `ProductCreated` between the two repos.
