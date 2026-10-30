# Integration Catalog

Every way services talk to each other. Generated contracts (OpenAPI, event schemas) go in
`architecture/contracts/`; this file is the human-readable index.

## Events

Topic naming (ADR 0002): **topic = `event_type`** (e.g. `ProductCreated`), key = `aggregate_id`.
Connector `postgres-cdc` on Kafka Connect `:9084` reads `store.outbox_events` with
`EventRouter` + `route.topic.replacement=${routedByValue}`.

| Event | Producer | Transport | Consumer | Payload | Status |
|-------|----------|-----------|----------|---------|--------|
| `ProductCreated` | stores-service (`OutboxEventHelper`, on create + import) | Outbox → Debezium `EventRouter` → Kafka | inventory-service `ProductCreatedConsumer` (group `product-consumer`, topic `ProductCreated`) | `eventId, eventType, occurredAt, merchantId, storeId, productId, skus[]`; key = `aggregate_id` (productId) | Live |
| `ProductUpdated` | stores-service (`OutboxEventHelper`, on update-product PUT) | Outbox → Debezium `EventRouter` → Kafka | inventory-service `ProductUpdatedConsumer` (group `inventory-product-updated`, topic `ProductUpdated`) | snapshot of catalog fields: `eventId, eventType, occurredAt, merchantId, storeId, productId, version, status, name, categoryId, skus[{id, sku, name, status, price, currency}]`; key = productId. Schema: `contracts/events/ProductUpdated.schema.json` | **Built** — built (stores-service#48, inventory-service#32; live once merged) ([flow](flows/product-updated.md)) |
| `OrderCreated` | order-service (not built) | Kafka | inventory-service `OrderCreatedEventConsumer` (group `order-consumer`) | not defined | Listener commented out |
| Reservation-expire tick | EventBridge rule `rate(1 minute)` | SQS `<profile>-reservation-expire-queue` | inventory-service `SqsReservationExpireConsumer` (1 in flight, visibility 90 s) | body ignored (trigger only); SQS `SentTimestamp` used to drop stale ticks | Live |

Payload contract for `ProductCreated` is duplicated: `stores-service/.../domain/event/ProductCreatedEvent`
and `inventory-service/.../infrastructure/message/dto/ProductCreatedEvent`. Change both together.
`ProductCreated` carries an optional `version` (always 0; consumers treat a missing value as 0; stores-service#48). Schemas: `contracts/events/`. Failed records go to `ProductCreated.DLT` / `ProductUpdated.DLT` (technical topics, not event types; inventory-service#32).
The consumer double-decodes the value (JSON string inside JSON) because of the Connect JSON converter.

## REST — stores-service (`:8048`)

Merchant (no merchant prefix): `POST /v1/store/merchants` (seller self-registration, 201 / 400 / 409 duplicate code), `GET /v1/store/merchants/{merchantId}` (200 / 404). Registration is not idempotent: a client that times out and retries gets 409 for its own code, and there is no lookup by code yet (follow-up: `GET /v1/store/merchants?code=`). The code must be 1–50 ASCII letters or digits (400 otherwise) and is stored trimmed and upper-case.

> **BREAKING (2026-10, merchant in Postgres):** `CreateStoreRequest` no longer has `merchantId`; the merchant comes from the path. A store can only be created for an existing merchant (404 otherwise; FK in the database).

Everything else is under the prefix `/v1/store/merchants/{merchantId}`:

> **Update product (built (stores-service#48, inventory-service#32; live once merged)):** `PUT /stores/{storeId}/products/{productId}` — full replace with `version` (200 / 400 limits, codes, SKU price rule / 404 / 409 version conflict or SKU code used by another product of the store (enforced by `UNIQUE (store_id, sku)`) / 422 status transition or ACTIVE without an ACTIVE SKU; unchanged content → 200 with the current version, nothing written, even with a stale version). Product responses (GET, create, PUT) carry `version`. See [flows/product-updated.md](flows/product-updated.md).

> **BREAKING (2026-10):** `tenant` renamed to `merchant` everywhere: paths `/v1/store/tenants/{tenantId}/…` → `/v1/store/merchants/{merchantId}/…`; body/response fields `tenantId` → `merchantId` in stores (`CreateStoreRequest`, `StoreDetailResponse`) and inventory (`CreateInventoryRequest`, `AdjustStockRequest`, `InventoryDetailResponse`, `StockMovementResponse`); event `ProductCreated.tenantId` → `merchantId` (no alias: old messages must not be replayed).

| Method | Path |
|--------|------|
| POST | `/stores` |
| GET | `/stores/{id}` |
| PUT | `/stores/{id}/close`, `/stores/{id}/reopen` |
| POST | `/stores/{id}/availability`, `/stores/{id}/availability/{availabilityId}/cancel` |
| PUT | `/stores/{storeId}/business-hours`, `/stores/{storeId}/configs` |
| POST | `/stores/{storeId}/products` (404 if the merchant does not exist or the store is not the merchant's; 400 if a SKU currency is not a 3-letter code, the price is negative, has more than 2 decimals or is a fractional VND amount, or price/dimensions exceed the column size or have more than 2 decimals; `images` optional; 409 for a SKU code already used in the store, removed codes included (BR-CAT-09); 400 over the BR-CAT-11 limits or for a null list element — also on Excel import, which reports FAILED; stores-service#48), `/stores/{storeId}/products/import` (200 with `status` SUCCESS or FAILED; FAILED means nothing was written — products and `ProductCreated` share one transaction; file read errors keep 400/422/500) |
| GET | `/stores/{storeId}/products/{productId}`, `/stores/{storeId}/products/search` (optional `notInCollectionId` leaves out that collection's products, 404 if it is not a collection of the store; order `sortBy` ∈ createdAt (default, DESC) / updatedAt / name / id, always `id` last; other `sortBy` or `direction` → 400; `direction` without `sortBy` applies to `createdAt`; `pageNumber` < 0 or `pageSize` < 1 → 400) |
| POST | `/stores/{storeId}/collections`, `.../{collectionId}/add-products`, `.../{collectionId}/remove-products` |
| GET | `/stores/{storeId}/collections`, `/stores/{storeId}/collections/{collectionId}`, `.../{collectionId}/products` (paged previews A→Z by name, `pageSize` 1–100) |

## REST — inventory-service (`:8058`, prefix `/v1/inventory`, no merchant in path yet)

| Method | Path | Visibility |
|--------|------|------------|
| POST | `/internal/v1/inventory/inventories` (create for a product's SKUs) | Internal only (`@Hidden`, blocked at gateway) |
| POST | `/v1/inventory/inventories/{inventoryId}` (adjust stock) | Public |
| GET | `/v1/inventory/inventories/{inventoryId}`, `/v1/inventory/inventories/products/{productId}` | Public |
| GET | `/v1/inventory/inventories/stock-movements/{inventoryId}` | Public |

## Front-end consumers

| Consumer | Calls | Notes |
|----------|-------|-------|
| **oms-web** (React, repo [`oms-web`](https://github.com/domt97/oms-web)) — Seller Centre `/seller` | All stores-service endpoints above (merchant-scoped), inventory-service `GET …/products/{productId}`, `GET …/{inventoryId}`, `POST …/{inventoryId}` (adjust), `GET …/stock-movements/{inventoryId}` | Through a reverse proxy on `/v1/store/` and `/v1/inventory/`; every call sends `X-Request-Id`. The product edit form (oms-web#6) calls the update-product PUT with the `version` from GET and sends back every field it does not edit (full replace); on 409 it re-reads the product to tell a stale version from a SKU code clash. The create form applies the same limits (100 SKUs, 20 images, 5000-character description) |
| **oms-web** — storefront `/` | Temporarily the same merchant-scoped reads (store detail, product search/detail) and the inventory read by product | Until the public catalog (BR-USR-05) exists; see open question 34. Changing these paths, adding auth or capping `pageSize` breaks the storefront |

## Synchronous calls between services

| From | To | Port | Status |
|------|----|------|--------|
| stores-service | inventory-service | `InventoryServiceClient.checkItemDetail(List<ItemDetailCheck>)` | Interface only, no adapter |
| stores-service | promotion-service | `PromotionServiceClient` | Empty interface |
