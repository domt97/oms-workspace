# Multi-tenancy & security — how the OMS does it today (snapshot)

Moved out of `SKILL.md` so the rules load without it. This is a hand-written snapshot, not a rule: before relying on
a line, check it against `architecture/generated/<service>.md` and the code — code wins. A gap listed here without an
open-question number is not yet in `architecture/open-questions.md`.

## OMS today (verified in code)
**Merchant model** (`vision.md`): the isolation unit is the **merchant** (seller company, often a chain, owning stores; formerly called *tenant* in code); launching in Vietnam (VND), not limited to one market or currency (BR-MER-01). Customers, carts and checkouts are platform level.
- `MerchantId` (oms-core typed ID). Merchants (`code`, `name`, `status`) live in stores-service's Postgres table `merchants` (`Merchant` aggregate, `MerchantRepository` port); `stores.merchant_id` has a foreign key to it. Other services only carry `merchant_id` (inventory gets it from `ProductCreated`).
- **Merchant `status` is never checked** (Q35): stores-service only tests that the merchant exists (`CreateStoreService`, `SearchProductService`, `GetStoreProductDetailService`, `StoreProductImportHandler`); inventory no longer looks merchants up at all. A suspended merchant keeps working.

**Isolation in data — stores-service**
- **Only the `stores` table has `merchant_id`** (column in `V1__init_store_tables.sql`; `UNIQUE (merchant_id, code)` added in `V4__add_unique_constraints.sql`).
- Every child table (products, SKUs, images, collections, availability, configs, business hours, addresses, `outbox_events`) is isolated **by `store_id` only**; `debezium_heartbeat` (connector heartbeat rows, no merchant data) is outside the domain.
- Isolation therefore depends on every use case first loading the store with `findByMerchantIdAndStoreId` (e.g. `GetStoreProductDetailService`) and then querying children by that store id.
- This is the intended hierarchical model (rule 1). The risk is a use case that skips the parent check (the collection use cases did until open question 27 was fixed).

**Isolation in data — inventory-service**
- Every table (`inventories`, `stock_reservations`, `stock_movements`, `stock_reservation_orders`, `outbox_events`) has `merchant_id`; `debezium_heartbeat` (connector heartbeat rows, no merchant data) is the exception.
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
- Log values that come from the caller are escaped (`LogSanitizer.escape`: control characters and U+2028/2029) so they cannot forge log lines. An inbound `X-Request-Id` is kept only if it matches `^[A-Za-z0-9._-]{1,64}$`, but it is still trusted as given: a caller can reuse another request's id. Acceptable until authentication exists. Only the keys configured in `app.logging.mdc.fields` reach the MDC from a request, each checked against its format and for control characters; never configure personal data (phone, email, names). Query values are caller-chosen on any route: never log a tenant id (`merchantId`) from the query. Reserved keys (`requestId`, `eventId`, `kafka*`, `sqsMessageId`) can never come from a request, so a caller cannot forge the cross-service join key.

## Known gaps
- No authentication or authorization; the path merchant is trusted; internal endpoints unprotected.
- inventory public reads are not merchant-scoped (open question 6).
- Merchant `status` ignored everywhere.
- S3 import uses the request's `path` as the **bucket** and `fileName` as the key (`ProductExcelReader` → `S3ObjectStorageReader.read(bucket, key)`). The caller can read any object the service's credentials allow; there is no merchant prefix (open question 25).
