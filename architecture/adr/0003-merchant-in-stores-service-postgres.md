# ADR 0003 — Merchants live in stores-service (Postgres), not in DynamoDB

Status: Accepted (2026-10-25)

## Context
The merchant (formerly "tenant") was a row in a shared DynamoDB table `<profile>_merchant_info`, read through
`oms-core` (`DynamoDbMerchantInfoRepository`) by stores-service (4 use cases) and inventory-service
(`AdjustStockService`). That made sense when "tenant" meant a SaaS customer with global configuration.

With tenant = merchant (BR-MER-02), the merchant is a business aggregate: it owns stores, has a status, and will
carry members/roles, commission and payouts. The DynamoDB design had these problems:
- two services read one table (a shared database, against system rule 1);
- no foreign key or transaction between a store and its merchant;
- one remote call per request;
- the table disappears on every LocalStack restart;
- its settings (`timeZone`, `currency`, `locale`) were obsolete: one platform currency, time zone per store.

## Decision
- stores-service owns the `Merchant` aggregate:
  - table `merchants` (`code` letters and digits only, unique and case-insensitive, `name`, `status` `ACTIVE`/`SUSPENDED`);
  - foreign key `stores.merchant_id → merchants.id`.
- Sellers register themselves: `POST /v1/store/merchants`, public, ACTIVE immediately (BR-MER-04..06).
- Creating a store takes the merchant from the path (`/v1/store/merchants/{merchantId}/stores`), no longer from the body.
- inventory-service does not look merchants up. It stores the `merchant_id` received with `ProductCreated`, and
  `Inventory.validateMerchantAndStore` checks requests against it.
- DynamoDB is removed from `oms-core`, both services and the LocalStack services in `development`.
- Local migration: stores `V1` was edited in place (no production data). Local databases are recreated: delete the
  connector, drop its replication slot (`debezium_store_v2_slot`, Postgres refuses to drop a database with a slot),
  recreate the databases, register the connector again (steps in the stores-service README).

## Consequences
- Merchant integrity is enforced by the database (FK, unique code). Merchant checks are a local primary-key lookup.
- Other services know only `merchant_id`. When merchant status must be enforced there (Q35), stores-service will
  publish `MerchantStatusChanged` and consumers keep a local copy (open question 32).
- Merchant members (OWNER/MANAGER/STAFF) and the owner link come with identity (BR-MER-07, Q36). A market level
  above merchants can be added later without changing merchants (`vision.md`, growth path).
- A breaking API change for create-store (`merchantId` removed from the body), acceptable because there are no clients yet.
