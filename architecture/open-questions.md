# Open Questions & Doc/Code Drift

Resolve each item, then delete it or turn it into an ADR. Last reviewed 2026-10-25. Items 1–3 (README drift, topic naming) resolved: stores-service#35, inventory-service#17, ADR 0002. Items 15, 16 (reservation status race, expiry run abort) resolved: inventory-service#27. Item 21 (overlapping reservation-expire ticks) resolved by bounding each sweep and dropping stale ticks: inventory-service#28; its large-volume remainder is item 22. Item 23 decided: stores-service keeps store-scoped child tables (hierarchical tenancy, `sa-multitenancy-security` rule 1); add `tenant_id` only for row-level security or tenant-wide queries.

## Local infrastructure

4. Debezium connector registration is not scripted in `development` (only documented in the stores README).
5. `development/docker/docker-compose.yml` mounts `./postgres/init` for Postgres, but the folder is not in the repo (DB/schema creation).
25. **Local AWS resources drifted, and the import bucket comes from the request.**
    - The DynamoDB table `localdev_tenant_info` is not in Terraform. It is created only by `oms-core/localstack/localstack.sh`, `stores-service/localstack/localstack.sh` or the inventory README.
    - Those scripts also create unused queues and an EventBridge bus.
    - In stores-service, `ProductExcelReader.read(path, fileName)` passes the request's `path` as the **S3 bucket** (`S3ObjectStorageReader.read(bucket, key)`), so a caller picks any bucket/key the service can read.
    - `aws.s3.store-product-bucket` (`S3Properties`) is unused, and its localdev value `localdev_store_products` differs from the Terraform bucket `localdev-store-products`.

## Correctness (inventory-service)

13. `ReserveStockService` is **not idempotent per order item** — replay reserves twice. Needs a uniqueness rule on (order_item_id, inventory_id) or a check.
14. Reserve / confirm / expire do **not write `StockMovement`** — audit trail incomplete.

## Correctness (stores-service)

24. **Excel import writes products and outbox events in separate transactions.**
    - `StoreProductImportHandler.process` is `@Transactional`, but it is called via `this.process(...)` from `AbstractImportTemplate.execute`, and `ImportProductService.execute` has no `@Transactional`. So the annotation is never applied.
    - `saveAllAndFlush` (products) and `outboxEventRepository.saveAll` (in `postImport`) each commit on their own. A failure between them leaves products with no `ProductCreated`, so inventory is never created. This breaks workspace rule 2.
    - The service catches every exception and returns `ImportResult{FAILED}` with HTTP 200, even after products were committed.
    - Also: duplicate product references in the file throw `IllegalStateException` from `Collectors.toMap`; there is no row limit; the whole file is processed in the request thread.
26. **SKU uniqueness differs between the two contexts.**
    - stores-service enforces `UNIQUE (product_id, sku)` only (`V3`), so two products in the same store may share a SKU.
    - inventory-service is unique on `(store_id, sku)`. `CreateInventoryService` logs "Inventory exists … with different productId … skipping", so the second product silently gets **no inventory**.
    - Decide whether a SKU is unique per store (then enforce it in stores-service), or key inventory by (store, product, sku).
27. **Collection use cases are not tenant/store-scoped.** The `tenantId`/`storeId` in the path are not checked against the data:
    - `AddProductCollectionService`, `RemoveProductFromCollectionService`, `GetStoreCollectionService` load the collection with `repository.getById(collectionId)` (`StoreCollectionPersistenceAdapter.getById` → `findById`).
    - `AddProductCollectionService` loads products with `findAllByIdIn(productIds)` (`createProductCollectionList`): another store's or tenant's products can be attached, and unknown ids are silently skipped.
    - `GetListStoreCollectionService` and `CreateStoreCollectionService` use `storeId` without checking it belongs to `tenantId` (create does check products belong to that store).
    - Fix: load the store by `(tenantId, storeId)`, the collection by `(storeId, id)`, products by `(storeId, ids)`, reject if any id is missing; add cross-tenant tests. (Found by reading code; not reproduced.)

## Reliability (messaging)

17. Kafka consumers have **no dead-letter topic / custom error handler**: spring-kafka default retries 10 times with no backoff, then skips the record — a failing message is silently lost.
18. SQS `reservation-expire` queue has **no DLQ / redrive policy** (`development/docker/infra/local/main.tf`).
19. **`outbox_events` is never cleaned up**: rows stay `PENDING` forever; no job deletes published rows.

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

6. inventory-service REST has **no `tenantId`** in path or header, unlike stores-service.
7. `InventoryServiceClient` (stores → inventory) and `PromotionServiceClient` have no adapter.
8. `ReleaseStockReservationUseCase` has no implementation; reserve/confirm have no entry points.
9. Only `ProductCreated` is published — no event for product/SKU update, deactivation, or store close.
10. `ProductCreatedEvent` is duplicated in both services; no shared schema / schema-registry subject.
11. Consumer group `product-consumer` is a generic name; may collide when more services consume products.
