---
name: sa-multitenancy-security
description: Multi-tenancy and security in the OMS — merchant isolation in data, queries, APIs and events, merchant lifecycle (`merchants` table in stores-service), authentication/authorization (not built yet), internal endpoints, secrets and PII in logs. Use for any change that reads or writes merchant data, adds an endpoint or event, handles credentials, or logs request data.
---
# Multi-tenancy & security

## OMS today (verified in code)
**Merchant model** (`vision.md`): the isolation unit is the **merchant** (seller company, often a chain, owning stores; formerly called *tenant* in code); launching in Vietnam (VND), not limited to one market or currency (BR-MER-01). Customers, carts and checkouts are platform level.
- `MerchantId` (oms-core typed ID). Merchants (`code`, `name`, `status`) live in stores-service's Postgres table `merchants` (`Merchant` aggregate, `MerchantRepository` port); `stores.merchant_id` has a foreign key to it. Other services only carry `merchant_id` (inventory gets it from `ProductCreated`).
- **Merchant `status` is never checked** (Q35): stores-service only tests that the merchant exists (`CreateStoreService`, `SearchProductService`, `GetStoreProductDetailService`, `StoreProductImportHandler`); inventory no longer looks merchants up at all. A suspended merchant keeps working.

**Isolation in data — stores-service**
- **Only the `stores` table has `merchant_id`** (column in `V1__init_store_tables.sql`; `UNIQUE (merchant_id, code)` added in `V4__add_unique_constraints.sql`).
- Every child table (products, SKUs, images, collections, availability, configs, business hours, addresses, `outbox_events`) is isolated **by `store_id` only**.
- Isolation therefore depends on every use case first loading the store with `findByMerchantIdAndStoreId` (e.g. `GetStoreProductDetailService`) and then querying children by that store id.
- This is the intended hierarchical model (rule 1). The risk is a use case that skips the parent check (the collection use cases did until open question 27 was fixed).

**Isolation in data — inventory-service**
- Every table (`inventories`, `stock_reservations`, `stock_movements`) has `merchant_id`.
- The public REST API takes no merchant (open question 6), and reads by id (`GET /v1/inventory/inventories/{id}`, `/products/{productId}`, stock movements) are not scoped by merchant.
- Only `AdjustStockService` calls `Inventory.validateMerchantAndStore`.

**Events**
- `ProductCreated` carries `merchantId`; the consumer copies it onto the new inventories.

**Authentication / authorization**
- **None.** There is no Spring Security in either service (`build.gradle`), no gateway, no token. The `merchantId` in the path is trusted as given.
- Internal endpoints (`/internal/v1/...`) are hidden from OpenAPI but **not protected**.

**Secrets and logs**
- Defaults in `application.yaml` contain LocalStack credentials (`AWS_ACCESS_KEY:test`), and inventory-service hard-codes the DB user and password `postgres`.
- `oms-core` `RequestResponseLoggingFilter` logs method, URI and **all headers** at INFO. It redacts `authorization`, `cookie`, `x-api-key` and similar headers, and token-like query params. It does not log bodies.

## Rules
1. **Where the merchant lives** (hierarchical tenancy):
   - A **top-level root** (e.g. `stores`) has `merchant_id NOT NULL`; per-merchant uniqueness includes it (`UNIQUE (merchant_id, code)`).
   - A **table owned by a merchant-scoped parent** (store products, collections, availability…) may rely on the parent key (`store_id`), as long as that parent never moves to another merchant. Do not duplicate `merchant_id` there.
   - A table in **another service** has no parent to join to, so it carries its own `merchant_id` (inventory does).
   - **Two owners**: merchant-owned data (merchant, store, catalog, inventory, order) is filtered by merchant (or a merchant-checked parent); customer-owned, platform-level data (customer, cart, checkout, payment) by customer. A checkout spans several merchants; each order it creates belongs to one merchant/store.
   - Add `merchant_id` to child tables only when needed: Postgres row-level security, merchant-wide queries/exports/deletion without the parent, or partitioning by merchant.
2. **Every query is scoped — never by id alone.**
   - Load the root by `(merchant_id, id)` (`findByMerchantIdAndStoreId`).
   - Load children by the checked parent: `WHERE store_id = :storeId AND id = :id`, and `WHERE store_id = :storeId AND id IN (:ids)` for lists of ids from the request (verify all were found).
   - Another merchant's or store's record → **404**, nothing written (don't leak existence with 403).
   - **Fixing a scoping gap also means checking the data.** The bug may already have written cross-merchant or cross-store rows, and the fix does not remove them. Write a query that finds rows breaking the invariant (e.g. a link whose child belongs to another store than its parent), run it, and ask the user what to do with any hits (migration, one-off script, or accept). Put the query in the PR body.
3. **Merchant in every event** (`merchantId` in the payload). Consumers validate it against the data they touch (e.g. inventory checks the store belongs to the same merchant).
4. **Merchant lifecycle**: decide what a non-active merchant can do (read-only? nothing?) and enforce it in one place. Until auth exists, that place is the use case that loads the `Merchant`; other services need a `MerchantStatusChanged` event (open question 32).
5. **Trust boundary (until auth is built)**: assume the caller is trusted, but design so it can be added without changing use cases:
   - `MerchantId` flows in the command object;
   - controllers take it from the path;
   - later, a filter will check the path merchant against the token claim.
   - Do not add new endpoints without a merchant.
6. **Internal endpoints** must be reachable only inside the network: a different port, network policy or gateway rule, plus service authentication when deployed. `@Hidden` is documentation, not protection.
7. **Secrets**:
   - never in code or committed YAML defaults for non-local profiles;
   - read from the environment or a secret manager;
   - local defaults only in the `localdev` profile.
   - In chat, never ask for tokens or keys (see `sa-analysis-checklist`).
8. **Logs**:
   - no secrets, tokens or full request bodies with PII (customer name, phone, address);
   - log ids, not personal data;
   - extend the filter's redaction list when adding a header.
9. **Excel/S3 input is untrusted**: validate size, row count and content; never trust a path or filename from the request to point outside the merchant's prefix.

## Checklist
- [ ] Every query in the change scoped by merchant (directly or through a merchant-scoped root)? Show the line.
- [ ] Cross-merchant test: an id that exists in another merchant → 404, nothing written.
- [ ] Ids in the request body (lists) checked to belong to the same store/merchant.
- [ ] Fixing a scoping gap: query for rows that already break the invariant, result shown, cleanup decided with the user.
- [ ] New table: top-level → `merchant_id NOT NULL` (in unique constraints and indexes); child of a merchant-scoped parent → parent key, or `merchant_id` if rule 1 says so.
- [ ] Event payload carries `merchantId`; consumer validates it.
- [ ] Merchant status handled (or explicitly out of scope).
- [ ] No secrets or PII in code, YAML defaults, logs, or event payloads beyond what the consumer needs.
- [ ] Internal endpoint? How is it kept internal?

## Known gaps
- No authentication or authorization; the path merchant is trusted; internal endpoints unprotected.
- inventory public reads are not merchant-scoped (open question 6).
- Merchant `status` ignored everywhere.
- S3 import uses the request's `path` as the **bucket** and `fileName` as the key (`ProductExcelReader` → `S3ObjectStorageReader.read(bucket, key)`). The caller can read any object the service's credentials allow; there is no merchant prefix (open question 25).
