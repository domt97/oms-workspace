# Integration Catalog

Every way services talk to each other. Generated contracts (OpenAPI, event schemas) go in
`architecture/contracts/`; this file is the human-readable index.

## Events

Topic naming (ADR 0002): **topic = `event_type`** (e.g. `ProductCreated`), key = `aggregate_id`.
Connector `postgres-cdc` on Kafka Connect `:9084` reads `store.outbox_events` with
`EventRouter` + `route.topic.replacement=${routedByValue}`; config in the `development` repo
(`docker/kafka-connect/connectors/postgres-cdc.json`, applied by `register-connectors.sh`, see its `docs/connectors.md`)
through the insert-only publication of `docker/kafka-connect/sql/store-outbox-cdc.sql`, with a heartbeat
(`store.debezium_heartbeat`, topic `__debezium-heartbeat.store`) (development#8). stores-service inserts each row with
`id` = payload `eventId` and deletes it in the same transaction (stores-service#59): the table is always empty and the
Kafka header `id` of `ProductCreated` / `ProductUpdated` equals the payload `eventId`.
Connector `inventory-outbox-cdc` reads `inventory.outbox_events` (DB `inventory`) through the insert-only publication of
`docker/kafka-connect/sql/inventory-outbox-cdc.sql`; its topics are pre-created by `docker/kafka/create-topics.sh` (development#7).
Every outbox-routed record carries the optional header **`correlationContext`** (ADR 0004): UTF-8 JSON object of the
producer's propagated MDC keys, e.g. `{"requestId":"abc"}`, from the outbox column `correlation_context`
(`table.fields.additional.placement`, `SimpleHeaderConverter`). Consumers must accept it absent, empty or invalid and
validate it (oms-core `MdcPropagation.restore`). It is not part of the payload schemas.

| Event | Producer | Transport | Consumer | Payload | Status |
|-------|----------|-----------|----------|---------|--------|
| `ProductCreated` | stores-service (`OutboxEventHelper`, on create + import) | Outbox → Debezium `EventRouter` → Kafka | inventory-service `ProductCreatedConsumer` (group `product-consumer`, topic `ProductCreated`) | `eventId, eventType, occurredAt, merchantId, storeId, productId, skus[]`; key = `aggregate_id` (productId) | Live |
| `ProductUpdated` | stores-service (`OutboxEventHelper`, on update-product PUT) | Outbox → Debezium `EventRouter` → Kafka | inventory-service `ProductUpdatedConsumer` (group `inventory-product-updated`, topic `ProductUpdated`) | snapshot of catalog fields: `eventId, eventType, occurredAt, merchantId, storeId, productId, version, status, name, categoryId, skus[{id, sku, name, status, price, currency}]`; key = productId. Schema: `contracts/events/ProductUpdated.schema.json` | **Built** — built (stores-service#48, inventory-service#32; live once merged) ([flow](flows/product-updated.md)) |
| `ReserveStock` *(command)* | order-service (not built), outbox | Outbox → Debezium → Kafka, key `orderId` | inventory-service (group `inventory-reserve-stock`) | `merchantId, storeId, orderId, lines[1..100]{orderItemId, productId, sku, quantity}`. Schema: `contracts/events/ReserveStock.schema.json` | **Designed** (ADR 0006) |
| `ConfirmStockReservation` *(command)* | order-service, at `PLACED` | same | inventory-service (group `inventory-confirm-stock-reservation`) | `merchantId, storeId, orderId` | **Designed** |
| `ReleaseStockReservation` *(command)* | order-service, on cancel / reject / timeout | same | inventory-service (group `inventory-release-stock-reservation`) | `merchantId, storeId, orderId, restock, reason` | **Designed** |
| `StockReserved` | inventory-service outbox (`StockReplyFactory`; connector `inventory-outbox-cdc`, development#7) | Outbox → Debezium → Kafka, key `orderId` | order-service | `causationId, expiresAt, lines[{orderItemId, sku, quantity, expiresAt}]` | **Built** (inventory-service#40) — published by `inventory-outbox-cdc` (development#7); topic pre-created (6 partitions) |
| `StockReservationRejected` | inventory-service | same | order-service | `orderReason?` (`ORDER_CLOSED`, `STALE_COMMAND`), `lines[{orderItemId, sku, reason}]`, no stock counts | **Built** (inventory-service#40) — published by `inventory-outbox-cdc` (development#7); topic pre-created (6 partitions) |
| `StockReservationConfirmed` / `StockReservationConfirmationFailed` | inventory-service | same | order-service | `lines[{orderItemId, status}]`; failure `reason` (`UNKNOWN_ORDER`, `ORDER_CLOSED`, `NOT_RESERVED`) | **Built** (inventory-service#40) — published by `inventory-outbox-cdc` (development#7); topic pre-created (6 partitions) |
| `StockReservationReleased` | inventory-service | same | order-service | `restock, lines[{orderItemId, status, restocked}]` | **Built** (inventory-service#40) — published by `inventory-outbox-cdc` (development#7); topic pre-created (6 partitions) |
| `StockReservationExpired` | inventory-service expiry job (no command) | same | order-service | `lines[{orderItemId, sku}]`; an order may get several, each for some lines | **Built** (inventory-service#40) — published by `inventory-outbox-cdc` (development#7); topic pre-created (6 partitions) |
| Reservation-expire tick | EventBridge rule `rate(1 minute)` | SQS `<profile>-reservation-expire-queue` | inventory-service `SqsReservationExpireConsumer` (1 in flight, visibility 90 s) | body ignored (trigger only); SQS `SentTimestamp` used to drop stale ticks | Live |

Payload contract for `ProductCreated` is duplicated: `stores-service/.../domain/event/ProductCreatedEvent`
and `inventory-service/.../infrastructure/message/dto/ProductCreatedEvent`. Change both together.
`ProductCreated` carries an optional `version` (always 0; consumers treat a missing value as 0; stores-service#48). Schemas: `contracts/events/`. Failed records go to `ProductCreated.DLT` / `ProductUpdated.DLT` (technical topics, not event types; inventory-service#32).
The consumer double-decodes the value (JSON string inside JSON) because of the Connect JSON converter.

Stock commands and replies (ADR 0006, [flow](flows/order-stock-reservation.md)). For order-service: as with `ProductCreated`, the record value is the payload as a JSON string inside JSON (decode twice, like inventory's `OutboxPayloadDecoder`); the Kafka header `id` equals the payload `eventId`; header `correlationContext` carries the producer's `requestId`. inventory's outbox rows are deleted in the same transaction (open question 19). Topics of the commands and replies are pre-created by `development` `docker/kafka/create-topics.sh`; the connector's technical heartbeat topic is `__debezium-heartbeat.inventory`. Commands come from order-service's outbox, replies from inventory's own outbox through a second connector (`inventory-outbox-cdc`, DB `inventory`, `development` repo, development#7). Every message carries `eventId, eventType, occurredAt, merchantId, storeId, orderId`; replies add `causationId` (the command's `eventId`); `StockReservationExpired` has no command (`causationId` null) and is deduplicated by `eventId`. Business outcomes are replies; contract errors go to `<topic>.DLT`. Inventory's `OrderCreatedEventConsumer` stub (topic `OrderCreated`) is replaced by these commands. Designed with them: DLTs `ReserveStock.DLT`, `ConfirmStockReservation.DLT`, `ReleaseStockReservation.DLT` (next to `ProductCreated.DLT` / `ProductUpdated.DLT`) and an internal replay endpoint `POST /internal/v1/inventory/dead-letters/{topic}/replay`.

## REST — stores-service (`:8048`)

Merchant (no merchant prefix): `POST /v1/store/merchants` (seller self-registration, 201 / 400 / 409 duplicate code), `GET /v1/store/merchants/{merchantId}` (200 / 404). Registration is not idempotent: a client that times out and retries gets 409 for its own code, and there is no lookup by code yet (follow-up: `GET /v1/store/merchants?code=`). The code must be 1–50 ASCII letters or digits (400 otherwise) and is stored trimmed and upper-case.

> **BREAKING (2026-10, merchant in Postgres):** `CreateStoreRequest` no longer has `merchantId`; the merchant comes from the path. A store can only be created for an existing merchant (404 otherwise; FK in the database).

Everything else is under the prefix `/v1/store/merchants/{merchantId}`:

> **Update product (built (stores-service#48, inventory-service#32; live once merged)):** `PUT /stores/{storeId}/products/{productId}` — full replace with `version` (200 / 400 limits, codes, SKU price rule / 404 / 409 version conflict or SKU code used by another product of the store (enforced by `UNIQUE (store_id, sku)`) / 422 status transition or ACTIVE without an ACTIVE SKU; unchanged content → 200 with the current version, nothing written, even with a stale version). Product responses (GET, create, PUT) carry `version`. See [flows/product-updated.md](flows/product-updated.md).

> **BREAKING (2026-10):** `tenant` renamed to `merchant` everywhere: paths `/v1/store/tenants/{tenantId}/…` → `/v1/store/merchants/{merchantId}/…`; body/response fields `tenantId` → `merchantId` in stores (`CreateStoreRequest`, `StoreDetailResponse`) and inventory (`CreateInventoryRequest`, `AdjustStockRequest`, `InventoryDetailResponse`, `StockMovementResponse`); event `ProductCreated.tenantId` → `merchantId` (no alias: old messages must not be replayed).

| Method | Path |
|--------|------|
| POST | `/stores` |
| GET | `/stores/{storeId}` |
| PUT | `/stores/{storeId}/close`, `/stores/{storeId}/reopen` |
| POST | `/stores/{storeId}/availability`, `/stores/{storeId}/availability/{storeAvailabilityId}/cancel` |
| PUT | `/stores/{storeId}/business-hours`, `/stores/{storeId}/configs` |
| POST | `/stores/{storeId}/products` (404 if the merchant does not exist or the store is not the merchant's; 400 if a SKU currency is not a 3-letter code, the price is negative, has more than 2 decimals or is a fractional VND amount, or price/dimensions exceed the column size or have more than 2 decimals; `images` optional; 409 for a SKU code already used in the store, removed codes included (BR-CAT-09); 400 over the BR-CAT-11 limits or for a null list element — also on Excel import, which reports FAILED; stores-service#48), `/stores/{storeId}/products/import` (BR-CAT-13: 200 SUCCESS, or 200 FAILED = the file broke a business rule and nothing was written (generic message for an internal error); 400 = the file can't be read as an import file — over 5 MB / 1,000 product / 10,000 SKU / 20,000 image rows, text or formatting budget, missing sheet, bad header, a cell that is not a valid number or id (sheet + row named), blank path/fileName; 404 = merchant, or store not the merchant's; 409 = an import for this store is already running; 422 = not an Excel file; 503 + Retry-After = the server stayed busy with other imports for 40 s; 500 = bucket/key missing. Synchronous: allow ~60 s (oms-web does). A retry after a timeout may say "SKU code in use" for an import that succeeded) |
| GET | `/stores/{storeId}/products/{productId}`, `/stores/{storeId}/products/search` (optional `notInCollectionId` leaves out that collection's products, 404 if it is not a collection of the store; order `sortBy` ∈ createdAt (default, DESC) / updatedAt / name / id, always `id` last; other `sortBy` or `direction` → 400; `direction` without `sortBy` applies to `createdAt`; `pageNumber` < 0 or `pageSize` < 1 → 400) |
| POST | `/stores/{storeId}/collections`, `.../{collectionId}/add-products`, `.../{collectionId}/remove-products` (add/remove are idempotent, BR-CAT-15: 200 with the collection as stored — a product already in / not in the collection is skipped (was 422); 400 missing or null id; 404 store, collection, or (add) a product not in the store; 409 changed by another request at the same moment (retry); 422 empty list) |
| GET | `/stores/{storeId}/collections`, `/stores/{storeId}/collections/{collectionId}`, `.../{collectionId}/products` (paged previews A→Z by name, `pageSize` 1–100) |

## REST — inventory-service (`:8058`, prefix `/v1/inventory`, no merchant in path yet)

| Method | Path | Visibility |
|--------|------|------------|
| POST | `/internal/v1/inventory/inventories` (create for a product's SKUs) | Internal only (`@Hidden`, blocked at gateway); kept for support. Rows it creates are **INACTIVE** (not orderable, BR-INV-08) until the catalog's next `ProductUpdated` sets their status — only when the request's `productId` is the product that owns the SKU in the catalog (otherwise the row stays INACTIVE); `ProductCreated` never changes an existing row, so to make such a row sellable, change the product in stores-service (decided 2026-11-06; inventory-service#39) |
| POST | `/v1/inventory/inventories/{inventoryId}` (adjust stock; the hold types `RESERVE`, `RESERVE_RELEASE`, `RESERVE_EXPIRE` are refused with 400, BR-INV-05; oms-web offers only the on-hand types) | Public |
| GET | `/v1/inventory/inventories/{inventoryId}`, `/v1/inventory/inventories/products/{productId}` | Public |
| GET | `/v1/inventory/inventories/stock-movements/{inventoryId}` | Public |

## Front-end consumers

| Consumer | Calls | Notes |
|----------|-------|-------|
| **oms-web** (React, repo [`oms-web`](https://github.com/domt97/oms-web)) — Seller Centre `/seller` | All stores-service endpoints above (merchant-scoped), inventory-service `GET …/products/{productId}`, `GET …/{inventoryId}`, `POST …/{inventoryId}` (adjust), `GET …/stock-movements/{inventoryId}` | Through a reverse proxy on `/v1/store/` and `/v1/inventory/`; every call sends `X-Request-Id`; both services keep it when it matches `^[A-Za-z0-9._-]{1,64}$` (else a new UUID), echo it in the response and log it as MDC `requestId`. The product edit form (oms-web#6) calls the update-product PUT with the `version` from GET and sends back every field it does not edit (full replace); on 409 it re-reads the product to tell a stale version from a SKU code clash. The create form applies the same limits (100 SKUs, 20 images, 5000-character description) |
| **oms-web** — storefront `/` | Temporarily the same merchant-scoped reads (store detail, product search/detail) and the inventory read by product | Until the public catalog (BR-USR-05) exists; see open question 34. Changing these paths, adding auth or capping `pageSize` breaks the storefront. |
| **oms-web** — both | `GET …/products/{productId}`; and (Seller Centre only) `GET …/stock-movements/{inventoryId}`, which will also return the hold types `RESERVE`, `RESERVE_RELEASE`, `RESERVE_EXPIRE` (BR-INV-05) | A SKU without an inventory record is not orderable (BR-CAT-04), nor an INACTIVE one (BR-INV-08). A SKU missing from the response has no record; the endpoint answers 404 when the whole product has none, which oms-web (storefront and Seller Centre, one adapter) also reads as "no record": answering `[]` instead keeps working, any other status for "no record" breaks it. oms-web must ship the change that shows the hold types (and the BR-CAT-04 rule) before inventory writes them |

## Synchronous calls between services

| From | To | Port | Status |
|------|----|------|--------|
| stores-service | inventory-service | `InventoryServiceClient.checkItemDetail(List<ItemDetailCheck>)` | Interface only, no adapter |
| stores-service | promotion-service | `PromotionServiceClient` | Empty interface |
