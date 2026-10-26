# System Overview

```mermaid
flowchart LR
    subgraph stores-service
        SAPI[REST /v1/store/merchants/...] --> SUC[Use cases]
        SUC --> SDB[(Postgres: store)]
        SUC --> OB[(outbox_events)]
    end
    OB -- WAL --> DBZ[Debezium<br/>Kafka Connect]
    DBZ -- ProductCreated --> K[(Kafka)]
    K --> PC[ProductCreatedConsumer]
    subgraph inventory-service
        PC --> IUC[Use cases]
        IAPI[REST /v1/inventory/inventories] --> IUC
        SQS[SqsReservationExpireConsumer] --> IUC
        IUC --> IDB[(Postgres: inventory)]
    end
    EB[EventBridge 1 min] --> Q[(SQS reservation-expire)] --> SQS
    ORD[order-service<br/>planned] -. OrderCreated .-> K
    SUC -. checkItemDetail .-> IAPI
```

## Tech stack (all services)

Java 17 · Spring Boot 3.2.3 · Spring Data JPA / Hibernate 6.4 · PostgreSQL 16 + Flyway ·
MapStruct 1.6.3 · Lombok · SpringDoc OpenAPI · Kafka (spring-kafka) · Spring Cloud AWS SQS ·
AWS SDK v2 (S3) · Gradle with `oms-core` composite build · LocalStack for local AWS.

## Service layout convention

```
com.dotran.oms.<context>/
├── domain/          model, valueobject, enums, event, exception — no Spring
├── application/     usecase (inbound ports), service (@UseCase impl), repository + client (outbound ports),
│                    command, dto, mapper, event (outbox factory), impex, jobs
└── infrastructure/  rest (@WebAdapter, dto, mapper, exception), persistence (@PersistenceAdapter, entity, jpa),
                     message (consumers + dto = ACL), mapper, cloud, swagger
```

Naming: `XxxUseCase` interface → `XxxService` implementation; `XxxCmd` input; `XxxDto` output;
`XxxRequest`/`XxxResponse` at the REST edge; `SpringDataXxxRepository` + `XxxPersistenceAdapter`.

Tests: JUnit per layer, mirrored package structure (domain model tests, service tests, adapter tests, controller tests).

## Multi-tenancy

Merchant isolation (`CLAUDE.md` rule 4, `vision.md`): merchant → store; customers are platform users.
- In stores-service, only `stores` has `merchant_id`; child tables are scoped by `store_id`.
- Every inventory-service table has `merchant_id`.

stores-service takes the merchant from the path (`/v1/store/merchants/{merchantId}/...`); inventory-service REST does not (open question 6).
Merchants are owned by stores-service (table `merchants`, FK from `stores`); inventory only stores the `merchant_id` it receives with `ProductCreated`.
