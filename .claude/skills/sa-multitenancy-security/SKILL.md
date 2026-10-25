---
name: sa-multitenancy-security
description: Multi-tenancy and security in the OMS — tenant isolation in data, queries, APIs and events, tenant lifecycle (DynamoDB tenant_info), authentication/authorization (not built yet), internal endpoints, secrets and PII in logs. Use for any change that reads or writes tenant data, adds an endpoint or event, handles credentials, or logs request data.
---
# Multi-tenancy & security

## OMS today (verified in code)
**Tenant model**
- `TenantId` (oms-core typed ID). Tenant metadata (`code`, `name`, `status`, `settings`) lives in DynamoDB `tenant_info`, read through `oms-core` `DynamoDbTenantInfoRepository.findByTenantId` and wrapped by each service's `TenantRepository` port.
- **Tenant `status` is never checked**: services only test that the tenant exists (`CreateStoreService`, `SearchProductService`, `GetStoreProductDetailService`, `StoreProductImportHandler`, `AdjustStockService`). A suspended tenant keeps working.

**Isolation in data — stores-service**
- **Only the `stores` table has `tenant_id`** (added in `V4__add_unique_constraints.sql`, with `UNIQUE (tenant_id, code)`).
- Every child table (products, SKUs, images, collections, availability, configs, business hours, addresses, `outbox_events`) is isolated **by `store_id` only**.
- Isolation therefore depends on every use case first loading the store with `findByTenantIdAndStoreId` (e.g. `GetStoreProductDetailService`) and then querying children by that store id.
- This is the intended hierarchical model (rule 1). The risk is a use case that skips the parent check: the collection use cases do (open question 27).

**Isolation in data — inventory-service**
- Every table (`inventories`, `stock_reservations`, `stock_movements`) has `tenant_id`.
- The public REST API takes no tenant (open question 6), and reads by id (`GET /v1/inventory/inventories/{id}`, `/products/{productId}`, stock movements) are not scoped by tenant.
- Only `AdjustStockService` calls `Inventory.validateTenantAndStore`.

**Events**
- `ProductCreated` carries `tenantId`; the consumer copies it onto the new inventories.

**Authentication / authorization**
- **None.** There is no Spring Security in either service (`build.gradle`), no gateway, no token. The `tenantId` in the path is trusted as given.
- Internal endpoints (`/internal/v1/...`) are hidden from OpenAPI but **not protected**.

**Secrets and logs**
- Defaults in `application.yaml` contain LocalStack credentials (`AWS_ACCESS_KEY:test`), and inventory-service hard-codes the DB user and password `postgres`.
- `oms-core` `RequestResponseLoggingFilter` logs method, URI and **all headers** at INFO. It redacts `authorization`, `cookie`, `x-api-key` and similar headers, and token-like query params. It does not log bodies.

## Rules
1. **Where the tenant lives** (hierarchical tenancy):
   - A **top-level root** (e.g. `stores`) has `tenant_id NOT NULL`; per-tenant uniqueness includes it (`UNIQUE (tenant_id, code)`).
   - A **table owned by a tenant-scoped parent** (store products, collections, availability…) may rely on the parent key (`store_id`), as long as that parent never moves to another tenant. Do not duplicate `tenant_id` there.
   - A table in **another service** has no parent to join to, so it carries its own `tenant_id` (inventory does).
   - Add `tenant_id` to child tables only when needed: Postgres row-level security, tenant-wide queries/exports/deletion without the parent, or partitioning by tenant.
2. **Every query is scoped — never by id alone.**
   - Load the root by `(tenant_id, id)` (`findByTenantIdAndStoreId`).
   - Load children by the checked parent: `WHERE store_id = :storeId AND id = :id`, and `WHERE store_id = :storeId AND id IN (:ids)` for lists of ids from the request (verify all were found).
   - Another tenant's or store's record → **404**, nothing written (don't leak existence with 403).
3. **Tenant in every event** (`tenantId` in the payload). Consumers validate it against the data they touch (e.g. inventory checks the store belongs to the same tenant).
4. **Tenant lifecycle**: decide what a non-active tenant can do (read-only? nothing?) and enforce it in one place. Until auth exists, that place is the use case that loads `TenantInfo`.
5. **Trust boundary (until auth is built)**: assume the caller is trusted, but design so it can be added without changing use cases:
   - `TenantId` flows in the command object;
   - controllers take it from the path;
   - later, a filter will check the path tenant against the token claim.
   - Do not add new endpoints without a tenant.
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
9. **Excel/S3 input is untrusted**: validate size, row count and content; never trust a path or filename from the request to point outside the tenant's prefix.

## Checklist
- [ ] Every query in the change scoped by tenant (directly or through a tenant-scoped root)? Show the line.
- [ ] Cross-tenant test: an id that exists in another tenant → 404, nothing written.
- [ ] Ids in the request body (lists) checked to belong to the same store/tenant.
- [ ] New table: top-level → `tenant_id NOT NULL` (in unique constraints and indexes); child of a tenant-scoped parent → parent key, or `tenant_id` if rule 1 says so.
- [ ] Event payload carries `tenantId`; consumer validates it.
- [ ] Tenant status handled (or explicitly out of scope).
- [ ] No secrets or PII in code, YAML defaults, logs, or event payloads beyond what the consumer needs.
- [ ] Internal endpoint? How is it kept internal?

## Known gaps
- No authentication or authorization; the path tenant is trusted; internal endpoints unprotected.
- Collection use cases load collections and products by id only (open question 27).
- inventory public reads are not tenant-scoped (open question 6).
- Tenant `status` ignored everywhere.
- S3 import uses the request's `path` as the **bucket** and `fileName` as the key (`ProductExcelReader` → `S3ObjectStorageReader.read(bucket, key)`). The caller can read any object the service's credentials allow; there is no tenant prefix (open question 25).
