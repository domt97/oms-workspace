# Testing strategy — how the OMS does it today (snapshot)

Moved out of `SKILL.md` so the rules load without it. This is a hand-written snapshot, not a rule: before relying on
a line, check it against `architecture/generated/<service>.md` and the code — code wins. A gap listed here without an
open-question number is not yet in `architecture/open-questions.md`.

## OMS today (verified in code)
**Test suites**
- Both services use JUnit 5 + Mockito only (`@ExtendWith(MockitoExtension.class)`, `@Mock`/`@InjectMocks`, `@DisplayName`), plus AssertJ from `spring-boot-starter-test`. There is no Spring context, no database and no broker.
  - stores-service: 37 test classes (service 17, domain 6, persistence 6, rest 5, event, impex, excel).
  - inventory-service: unit test classes for service, domain, rest, message, persistence and config, plus an
    `integrationTest` suite (`src/integrationTest`: `StockSqlIT`, `StockCommandsIT`, `StockConcurrencyIT`, `StockCommandTransactionIT`, `OutboxSqlIT`, `StockRepliesIT`, `OutboxFailureIT`, `StockCommandConsumersIT`, `StockCommandErrorClassificationIT`). The last two call the Kafka listener methods and the error handler directly (no broker): JSON record in → rows and the reply in the WAL out, and real timeout exceptions → retry / DLT classification; what the listener container does with the `@KafkaListener` settings stays a manual check. The outbox ITs read what Debezium would see through a `test_decoding` slot (`support/WalSlot`, container `wal_level=logical`): per reply one INSERT + DELETE in the xid of the business change, nothing for rolled-back transactions; payloads validated against the copied contract schemas.
- **Controller tests call the controller method directly** (e.g. `StoreCollectionControllerTest`, `controller.create(...)`). They do **not** exercise URL mapping, JSON (de)serialisation, `@Valid` constraints, status codes or `GlobalExceptionHandler` mapping.
- Persistence adapter unit tests mock the Spring Data repository. In stores-service **native SQL, JPQL, constraints, indexes, Flyway migrations and `@Transactional` boundaries are not exercised by any test**; in inventory-service the `integrationTest` suite covers the stock SQL (below).
- `@ConfigurationProperties` validation is tested with a plain `jakarta.validation.Validator` (`ReservationExpiryPropertiesTest`).

**CI: unit tests everywhere, integration tests in inventory-service**
- `.github/workflows/ci.yml` runs `./gradlew test` on every PR and push to `develop`/`master` (services, against the pinned `coreVersion` from GitHub Packages; `core-pin` rejects `-rc` pins), oms-core's own tests plus a publication dry run, and `npm run build` for oms-web (workspace CLAUDE.md → CI).
- inventory-service has a Gradle JVM test suite **`integrationTest`** (Testcontainers `postgres:16-alpine`, version pinned in `build.gradle`) run by the CI job `Integration tests` (not a required check yet). Base class `support/PostgresIT`: `@DataJpaTest` with the real database (`replace = NONE`), Flyway V1..Vn into schema `inventory` (the Flyway URL/user/password are overridden too), the persistence adapters and the stock services imported, **no surrounding test transaction** (`NOT_SUPPORTED`; each call commits), tables truncated before each test. Races use a start latch, futures awaited with a timeout, and assertions on committed rows; timeouts are asserted by Spring exception class, and by SQLState where there is one: `lock_timeout` → `PessimisticLockingFailureException` (55P03), `statement_timeout` → `QueryTimeoutException` (57014), a statement after the transaction deadline → `TransactionTimedOutException` (see the flow `order-stock-reservation.md`, *Timeouts*).
- **Still not exercised by anything:** stores-service SQL and migrations, Kafka/SQS delivery, Debezium routing, URL mapping and JSON (de)serialisation over HTTP. These stay manual checks written in the PR.

**Runtime checks done instead**
- Changes to SQL have been checked by hand against local Postgres (EXPLAIN, run against seeded data), as in inventory-service#27 and #28.

## Known gaps
- Integration tests exist only for inventory-service's Postgres SQL; none for Kafka, SQS, S3, or stores-service; no MockMvc controller tests.
- The `Integration tests` CI job is not a required check yet.
- No contract tests for `ProductCreated` between the two repos.
