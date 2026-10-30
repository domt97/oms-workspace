# Open Questions & Doc/Code Drift

Resolve each item, then delete it or turn it into an ADR. Last reviewed 2026-10-29. Items 26 (SKU unique per store), 41 (SKU code length) and 42 (legacy products over the caps: none locally, local DBs recreated) resolved by update-product: stores-service#48, inventory-service#32. Items 1–3 (README drift, topic naming) resolved: stores-service#35, inventory-service#17, ADR 0002. Items 15, 16 (reservation status race, expiry run abort) resolved: inventory-service#27. Item 21 (overlapping reservation-expire ticks) resolved by bounding each sweep and dropping stale ticks: inventory-service#28; its large-volume remainder is item 22. Item 28 (code called the merchant *tenant*) resolved by the tenant → merchant rename in oms-core, stores-service and inventory-service (2026-10), with migrations edited in place (local databases recreated). Item 29 (create-store took the merchant from the body) resolved with the move of merchants to Postgres (merchant from the path, FK). Open-questions item 34 (allowed characters in a merchant code) decided: ASCII letters and digits, enforced in `Merchant.register` and `ck_merchants_code` (BR-MER-04). Item 27 (collection use cases not merchant/store-scoped) resolved: stores-service#45 — store checked against the merchant, collection loaded by `(storeId, id)`, products by `(storeId, ids)`. Item 23 decided: stores-service keeps store-scoped child tables (hierarchical tenancy, `sa-multitenancy-security` rule 1); add `merchant_id` only for row-level security or merchant-wide queries.

## Local infrastructure

4. Debezium connector registration is not scripted in `development` (only documented in the stores README).
5. `development/docker/docker-compose.yml` mounts `./postgres/init` for Postgres, but the folder is not in the repo (DB/schema creation).
25. **Local AWS resources drifted, and the import bucket comes from the request.**
    - The LocalStack scripts in `oms-core/localstack/` and `stores-service/localstack/` create unused queues and an EventBridge bus (DynamoDB is gone since merchants moved to Postgres).
    - In stores-service, `ProductExcelReader.read(path, fileName)` passes the request's `path` as the **S3 bucket** (`S3ObjectStorageReader.read(bucket, key)`), so a caller picks any bucket/key the service can read.
    - `aws.s3.store-product-bucket` (`S3Properties`) is unused, and its localdev value `localdev_store_products` differs from the Terraform bucket `localdev-store-products`.

## Correctness (inventory-service)

13. `ReserveStockService` is **not idempotent per order item** — replay reserves twice. Needs a uniqueness rule on (order_item_id, inventory_id) or a check.
14. Reserve / confirm / expire do **not write `StockMovement`** — audit trail incomplete.
39. **Reserve does not check inventory status** (BR-INV-08): `reserve` SQL and `Inventory.reserve` accept an INACTIVE inventory. Harmless until order-service calls reserve; add `AND status = 'ACTIVE'` and a domain check then.

## Correctness (stores-service)

24. **Excel import is synchronous and unbounded.** Products and their `ProductCreated` outbox rows are now written in one transaction (stores-service fix/import-transaction, 2026-10-30), so a FAILED import writes nothing. Still open: no row cap, the whole workbook is loaded into memory and one transaction holds a Hikari connection (pool 10) for the whole import, inside the request thread (→ async import, 202 + job); database error text leaks into `errorMessage`; merchant/store not found answers 200 FAILED although the OpenAPI declares 404; a client retry after a timeout gets FAILED "SKU code in use" for an import that actually succeeded; SKU/image rows whose product reference has no product row are not imported (logged as WARN, decided 2026-10-30) but their SKU codes are still validated.
    - `StoreProductImportHandler.process` is `@Transactional`, but it is called via `this.process(...)` from `AbstractImportTemplate.execute`, and `ImportProductService.execute` has no `@Transactional`. So the annotation is never applied.
    - `saveAllAndFlush` (products) and `outboxEventRepository.saveAll` (in `postImport`) each commit on their own. A failure between them leaves products with no `ProductCreated`, so inventory is never created. This breaks workspace rule 2.
    - The service catches every exception and returns `ImportResult{FAILED}` with HTTP 200, even after products were committed.
    - Also: duplicate product references in the file throw `IllegalStateException` from `Collectors.toMap`; there is no row limit; the whole file is processed in the request thread.
35. **Two concurrent add-products for the same product return 500, not 409.** The second insert hits `uk_product_collections_collection_product` (V6) and the `DataIntegrityViolationException` falls into the catch-all handler. Map it to 409 for this endpoint (a global mapping would change other paths).
36. **No cap on `productIds`** in create-collection (body) and add/remove-products (query string). Cost grows with the list: the query string length on add/remove, the size of the `IN` list in the product check (pgjdbc rejects more than 65,535 bind parameters), and one `nextval` per link row (`product_collection_seq`, `allocationSize = 1`). Decide a maximum (new API rule) and enforce it with `@Size`.
37. **Product search and collection products sort in memory.** Both filter by `store_id` (`idx_store_products_store`, V3) and order by `created_at, id` or `name, id`, so every page reads and sorts all of the store's products (collection membership is checked through `uk_product_collections_collection_product`, V6). Fine at the assumed hundreds to a few thousand products per store; add `(store_id, created_at, id)` / `(store_id, name, id)` indexes if EXPLAIN shows large sorts. Name order follows the database collation (local image `en_US.utf8`): confirm Vietnamese names sort as expected on the real database.
38. **Currency is not checked against VND** (BR-MER-01, BR-STO-03): create-store and update-configs accept any 3-letter code, and SKUs accept any 3-letter code (decided 2026-10-28; only VND prices must be whole, stores-service#47). oms-web always sends `VND`. Nothing stops one product mixing currencies: `StoreProduct.getMinPrice/getMaxPrice` compare raw amounts across currencies and `getCurrency()` returns the first SKU's, and product search filters price ranges without the currency (`StoreProductPersistenceAdapter`), so USD 9.99 matches a VND 0–10,000 range. Decide before cart/checkout whether a non-VND SKU can be sold, whether one product may mix currencies, and whether SKUs must match the store currency. Also, Excel import has no bean validation, so a weight/size above `NUMERIC(10,2)` fails the whole import with a database error instead of a clear message.

31. **`Store.ownerId` is a `CustomerId`** (`stores.owner_id`): a store's "owner" is modelled as a customer. With merchants and (later) merchant members (BR-MER-07) this field is redundant and mistyped; drop it or replace it when members are built.

33. **Merchant self-registration is public with no authentication or rate limit.** `POST /v1/store/merchants` lets anyone create merchants and reserve codes. Business side: Q36 (owner link through identity), Q37 (KYC / PENDING). Until identity exists, do not expose the endpoint outside the local network.
34. **The storefront (oms-web) uses seller endpoints because there is no public catalog yet.** oms-web aggregates merchant-scoped stores-service calls over a bounded list of shops and reads `GET /v1/inventory/inventories/products/{productId}`, which is unscoped (item 6) and returns on-hand, reserved and `merchantId` to the shopper's browser (oms-web shows only a status, BR-CAT-04). Consequences: **the public catalog/search read model (BR-USR-05) must ship before stores-service requires seller authentication**, or the storefront breaks; and a page-size cap or auth on these endpoints is a breaking change for oms-web (oms-web `docs/architecture.md` §4).
43. **Removed SKU rows grow without limit per product.** Soft-removed SKUs stay in `product_skus` (their codes stay reserved, BR-CAT-09) and every update-product loads them. The 100-SKU cap counts only SKUs in the request. Decide a purge or a cap on removed rows if products get edited a lot.
44. **A GET can show version v with SKUs of v+1.** GET product loads the product row and its SKUs/images in separate statements (READ COMMITTED), so an update committing in between shows a mixed state. The next PUT with that version correctly gets 409; consider a fetch join or REPEATABLE READ for GET.
45. **`outbox_events.id` differs from the payload `eventId`.** `OutboxEventPersistenceAdapter` sets an id on an entity whose id is `@GeneratedValue`, so JPA merges and generates a new one (seen for `ProductCreated` and `ProductUpdated`). Consumers use the payload `eventId` (and inventory deduplicates by version), so nothing breaks today; fix it before anything relies on the outbox row id (e.g. Debezium's event-id header).

## Reliability (messaging)

17. Kafka DLT exists for inventory's catalog consumers (inventory-service#32: `<topic>.DLT`, contract errors at once, DB outages retried until back), but there is **no alerting on DLT records and no replay tool** (see 40); records are only visible as ERROR logs.
18. SQS `reservation-expire` queue has **no DLQ / redrive policy** (`development/docker/infra/local/main.tf`).
19. **`outbox_events` is never cleaned up**: rows stay `PENDING` forever; no job deletes published rows.
30. **Kafka topics are auto-created** with broker defaults (1 partition): `ProductCreated` exists only because the broker auto-creates it. Create topics explicitly (partitions, retention) in `development` before consumers need to scale.
40. **No way to resync a product to inventory.** If a `ProductCreated`/`ProductUpdated` is skipped (open question 17) or lost (before stores-service fix/import-transaction, an Excel import could commit products without their event), inventory stays stale until the next update of that product. Add a republish (stores) or resync (inventory) tool.

## Scale (inventory-service)

22. **Reservation expiry has a throughput ceiling and no backlog signal.** Since inventory-service#28 each tick is bounded (keyset pages of 500, 40 s budget), but:
    - `markExpired` updates **one row per statement** (`transitionStatus`), so a sweep costs one DB round trip per reservation. Measured locally ≈ 3k reservations/s; with production latency estimated ≈ 1k/s → roughly 40k per tick (estimate, not measured). If more reservations expire per minute than that, the backlog grows.
    - **Instances do not share the work**: every sweep reads from the start in the same `(expires_at, id)` order. After downtime all instances run (stale-tick drop fails open) and contend for the same rows — safe because of the guard, but no faster than one instance.
    - **No metrics**: only logs. Nothing reports the expired-but-still-`RESERVED` count or the age of the oldest one, so a growing backlog is invisible.
    - A failing inventory near the front of the order (e.g. already-corrupted `reserved_quantity`) is retried first on every tick.
    Options when volume requires it: set-based `markExpired` (`UPDATE … WHERE id IN (…) AND status = 'RESERVED' RETURNING id`) plus one release per inventory; claim pages with `SELECT … FOR UPDATE SKIP LOCKED LIMIT n` so instances split the work; Micrometer gauges (backlog, oldest expired age) with an alert; `CREATE INDEX CONCURRENTLY` for future indexes on large tables.

## Code hygiene

20. `oms-core/.../domain/page/PagedResult.java` imports Spring Data `Page` — the only framework dependency inside a `domain` package.

## Design decisions pending (decide when a feature needs them)

6. inventory-service REST has **no `merchantId`** in path or header, unlike stores-service.
7. `InventoryServiceClient` (stores → inventory) and `PromotionServiceClient` have no adapter.
8. `ReleaseStockReservationUseCase` has no implementation; reserve/confirm have no entry points.
9. No event for **store** close or status change (`StoreStatusChanged` proposed). Product and SKU changes travel as `ProductUpdated` ([flow](flows/product-updated.md)).
10. `ProductCreatedEvent` is duplicated in both services; no shared schema / schema-registry subject.
11. Consumer group `product-consumer` is a generic name; may collide when more services consume products. Do not rename it (with `earliest` a new group replays all `ProductCreated` history); new consumers use specific names (planned: `inventory-product-updated`).
32. **Merchant status is not enforced outside stores-service.** Inventory (and later order) only know `merchant_id`. When Q35 decides what a suspended merchant may do, publish `MerchantStatusChanged` from stores-service and keep a local copy in the consumers.
