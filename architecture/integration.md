# Integration Catalog

Every way services talk to each other. Generated contracts (OpenAPI, event schemas) go in
`architecture/contracts/`; this file is the human-readable index.

## Events

Topic naming (ADR 0002): **topic = `event_type`** (e.g. `ProductCreated`), key = `aggregate_id`.
Connector `postgres-cdc` on Kafka Connect `:9084` reads `store.outbox_events` with
`EventRouter` + `route.topic.replacement=${routedByValue}`; config in the `development` repo
(`docker/kafka-connect/connectors/postgres-cdc.json`, applied by `register-connectors.sh`, see its `docs/connectors.md`)
through the insert-only publication of `docker/kafka-connect/sql/store-outbox-cdc.sql`, with a heartbeat
(`store.debezium_heartbeat`, topic `__debezium-heartbeat.store`). stores-service inserts each row with
`id` = payload `eventId` and deletes it in the same transaction: the table is always empty and the
Kafka header `id` of `ProductCreated` / `ProductUpdated` equals the payload `eventId`.
Connector `inventory-outbox-cdc` reads `inventory.outbox_events` (DB `inventory`) through the insert-only publication of
`docker/kafka-connect/sql/inventory-outbox-cdc.sql`; its topics are pre-created by `docker/kafka/create-topics.sh`.
Every outbox-routed record carries the optional header **`correlationContext`** (ADR 0004): UTF-8 JSON object of the
producer's propagated MDC keys, e.g. `{"requestId":"abc"}`, from the outbox column `correlation_context`
(`table.fields.additional.placement`, `SimpleHeaderConverter`). Consumers must accept it absent, empty or invalid and
validate it (oms-core `MdcPropagation.restore`). It is not part of the payload schemas.

| Event | Producer | Transport | Consumer | Payload | Status |
|-------|----------|-----------|----------|---------|--------|
| `ProductCreated` | stores-service (`OutboxEventHelper`, on create + import) | Outbox → Debezium `EventRouter` → Kafka | inventory-service `ProductCreatedConsumer` (group `product-consumer`, topic `ProductCreated`) | `eventId, eventType, occurredAt, merchantId, storeId, productId, skus[]`; key = `aggregate_id` (productId) | Live |
| `ProductUpdated` | stores-service (`OutboxEventHelper`, on update-product PUT) | Outbox → Debezium `EventRouter` → Kafka | inventory-service `ProductUpdatedConsumer` (group `inventory-product-updated`, topic `ProductUpdated`) | snapshot of catalog fields: `eventId, eventType, occurredAt, merchantId, storeId, productId, version, status, name, categoryId, skus[{id, sku, name, status, price, currency}]`; key = productId. Schema: `contracts/events/ProductUpdated.schema.json` | **Built** ([flow](flows/product-updated.md)) |
| `PlaceCheckout` *(command)* | cart-service (not built), outbox, in the transaction that sets the cart `CHECKING_OUT` | Outbox → Debezium → Kafka, key `cartId` | order-service (group `order-place-checkout`) | `customerId, cartId, cartVersion, requestedAt, delivery, stores[{merchantId, storeId, quoteId, lines}]`, no prices (ADR 0007) | **Consumed** by order-service (`PlaceCheckoutConsumer`, listener off by default until the go-live gates, D1); producer planned |
| `CheckoutPlaced` / `CheckoutRejected` | order-service, outbox (connector `order-outbox-cdc`) | same, key `cartId` | cart-service | `causationId, cartId, cartVersion, checkoutId, orders[]` / `reasons[{storeId?, sku?, code}]` | **Published**: `CheckoutRejected` for pre-reserve rejections, STALE, CONTENT_MISMATCH, a daily cap and a refused or timed-out reserve (all reasons at once, D3); `CheckoutPlaced` when every order is reserved, `causationId` = the stored command's (a copy of the command gets it again with its own). Stored and re-sent the same to every copy |
| `ReserveStock` *(command)* | order-service, outbox, in the placement transaction | Outbox → Debezium → Kafka, key `orderId` | inventory-service (group `inventory-reserve-stock`) | `merchantId, storeId, orderId, lines[1..100]{orderItemId, productId, sku, quantity}`. Schema: `contracts/events/ReserveStock.schema.json` | **Built** both sides: producer order-service (one per order, new `orderItemId`s), consumer `ReserveStockConsumer` (ADR 0006) |
| `ConfirmStockReservation` *(command)* | order-service, at `PLACED`; re-sent from 150 s, doubling to 10 min, until a reply | same | inventory-service (group `inventory-confirm-stock-reservation`) | `merchantId, storeId, orderId` | **Built** both sides (`ConfirmStockReservationConsumer`) |
| `ReleaseStockReservation` *(command)* | order-service, on reject / reserve timeout / confirmation failure (later: cancel); re-sent like the confirm | same | inventory-service (group `inventory-release-stock-reservation`) | `merchantId, storeId, orderId, restock, reason` (`CHECKOUT_REJECTED`, `RESERVE_TIMEOUT`, `STOCK_NOT_CONFIRMED`, restock true) | **Built** both sides (`ReleaseStockReservationConsumer`) |
| `StockReserved` | inventory-service outbox (`StockReplyFactory`; connector `inventory-outbox-cdc`) | Outbox → Debezium → Kafka, key `orderId` | order-service (group `order-stock-reserved`) | `causationId, expiresAt, lines[{orderItemId, sku, quantity, expiresAt}]` | **Built** — published by `inventory-outbox-cdc`; topic pre-created (6 partitions); consumed by order-service `StockReplyConsumers` |
| `StockReservationRejected` | inventory-service | same | order-service (group `order-stock-reservation-rejected`) | `orderReason?` (`ORDER_CLOSED`, `STALE_COMMAND`), `lines[{orderItemId, sku, reason}]`, no stock counts | **Built** — published by `inventory-outbox-cdc`; topic pre-created (6 partitions); consumed by order-service |
| `StockReservationConfirmed` / `StockReservationConfirmationFailed` | inventory-service | same | order-service (groups `order-stock-reservation-confirmed`, `order-stock-reservation-confirmation-failed`) | `lines[{orderItemId, status}]`; failure `reason` (`UNKNOWN_ORDER`, `ORDER_CLOSED`, `NOT_RESERVED`) | **Built** — published by `inventory-outbox-cdc`; topic pre-created (6 partitions); consumed by order-service |
| `StockReservationReleased` | inventory-service | same | order-service (group `order-stock-reservation-released`) | `restock, lines[{orderItemId, status, restocked}]` | **Built** — published by `inventory-outbox-cdc`; topic pre-created (6 partitions); consumed by order-service |
| `StockReservationExpired` | inventory-service expiry job (no command) | same | order-service (not consumed yet, open question 69) | `lines[{orderItemId, sku}]`; an order may get several, each for some lines | **Built** — published by `inventory-outbox-cdc`; topic pre-created (6 partitions) |
| Reservation-expire tick | EventBridge rule `rate(1 minute)` | SQS `<profile>-reservation-expire-queue` | inventory-service `SqsReservationExpireConsumer` (1 in flight, visibility 90 s) | body ignored (trigger only); SQS `SentTimestamp` used to drop stale ticks | Live |

Payload contract for `ProductCreated` is duplicated: `stores-service/.../domain/event/ProductCreatedEvent`
and `inventory-service/.../infrastructure/message/dto/ProductCreatedEvent`. Change both together.
`ProductCreated` carries an optional `version` (always 0; consumers treat a missing value as 0). Schemas: `contracts/events/`. Failed records go to `ProductCreated.DLT` / `ProductUpdated.DLT` (technical topics, not event types).
The consumer double-decodes the value (JSON string inside JSON) because of the Connect JSON converter.

Stock commands and replies (ADR 0006, [flow](flows/order-stock-reservation.md)). For order-service: as with `ProductCreated`, the record value is the payload as a JSON string inside JSON (decode twice, like inventory's `OutboxPayloadDecoder`); the Kafka header `id` equals the payload `eventId`; header `correlationContext` carries the producer's `requestId`. inventory's outbox rows are deleted in the same transaction (ADR 0006). Topics of the commands and replies are pre-created by `development` `docker/kafka/create-topics.sh`; the connector's technical heartbeat topic is `__debezium-heartbeat.inventory`. Commands come from order-service's outbox, replies from inventory's own outbox through a second connector (`inventory-outbox-cdc`, DB `inventory`, `development` repo). Every message carries `eventId, eventType, occurredAt, merchantId, storeId, orderId`; replies add `causationId` (the command's `eventId`); `StockReservationExpired` has no command (`causationId` null) and is deduplicated by `eventId`. order-service deduplicates the replies to commands by the order's state, never by `causationId` (a re-sent command has a new `eventId`; `causationId` is only logged, ADR 0006 obligation 4); a reply for another merchant's or store's order, or with lines that are not the order's, goes to its `<topic>.DLT` (five reply DLTs, created by order-service with 1 partition). Business outcomes are replies; contract errors go to `<topic>.DLT`. Inventory's `OrderCreatedEventConsumer` stub (topic `OrderCreated`) is removed; these commands replace it. The consumers have DLTs `ReserveStock.DLT`, `ConfirmStockReservation.DLT`, `ReleaseStockReservation.DLT` (next to `ProductCreated.DLT` / `ProductUpdated.DLT`; created by inventory-service with 1 partition). Inventory dead-letters a command whose `eventType` is not its topic's message type (the payloads overlap), whose `quantity` is not a whole number or whose `restock` is not a JSON boolean; what a consumer does with each kind of record is in the flow (*Command consumers*). A command in a DLT gets no reply. Still designed, not built (open question 17): an internal replay endpoint `POST /internal/v1/inventory/dead-letters/{topic}/replay` and alerting.

## REST — stores-service (`:8048`)

Merchant (no merchant prefix): `POST /v1/store/merchants` (seller self-registration, 201 / 400 / 409 duplicate code), `GET /v1/store/merchants/{merchantId}` (200 / 404). Registration is not idempotent: a client that times out and retries gets 409 for its own code, and there is no lookup by code yet (follow-up: `GET /v1/store/merchants?code=`). The code must be 1–50 ASCII letters or digits (400 otherwise) and is stored trimmed and upper-case.

> `CreateStoreRequest` has no `merchantId`: the merchant comes from the path. A store can only be created for an existing merchant (404 otherwise; FK in the database).

Everything else is under the prefix `/v1/store/merchants/{merchantId}`:

> **Update product:** `PUT /stores/{storeId}/products/{productId}` — full replace with `version` (200 / 400 limits, codes, SKU price rule / 404 / 409 version conflict or SKU code used by another product of the store (enforced by `UNIQUE (store_id, sku)`) / 422 status transition or ACTIVE without an ACTIVE SKU; unchanged content → 200 with the current version, nothing written, even with a stale version). Product responses (GET, create, PUT) carry `version`. See [flows/product-updated.md](flows/product-updated.md).

> There is no alias for the old `tenant` names (`tenantId` fields, `/v1/store/tenants/…` paths): old `ProductCreated` messages carrying `tenantId` must not be replayed.

| Method | Path |
|--------|------|
| POST | `/stores` |
| GET | `/stores/{storeId}` |
| PUT | `/stores/{storeId}/close`, `/stores/{storeId}/reopen` |
| POST | `/stores/{storeId}/availability`, `/stores/{storeId}/availability/{storeAvailabilityId}/cancel` |
| PUT | `/stores/{storeId}/business-hours`, `/stores/{storeId}/configs` |
| POST | `/stores/{storeId}/products` (404 if the merchant does not exist or the store is not the merchant's; 400 if a SKU currency is not a 3-letter code, the price is negative, has more than 2 decimals or is a fractional VND amount, or price/dimensions exceed the column size or have more than 2 decimals; `images` optional; 409 for a SKU code already used in the store, removed codes included (BR-CAT-09); 400 over the BR-CAT-11 limits or for a null list element — also on Excel import, which reports FAILED), `/stores/{storeId}/products/import` (BR-CAT-13: 200 SUCCESS, or 200 FAILED = the file broke a business rule and nothing was written (generic message for an internal error); 400 = the file can't be read as an import file — over 5 MB / 1,000 product / 10,000 SKU / 20,000 image rows, text or formatting budget, missing sheet, bad header, a cell that is not a valid number or id (sheet + row named), a `fileName` that is not a plain file name (BR-CAT-16); 404 = merchant, or store not the merchant's, or no such file in the store's import folder; 409 = an import for this store is already running; 422 = not an Excel file; 503 + Retry-After = the server stayed busy with other imports for 40 s; 500 = import bucket missing, access denied or a storage error. The body is `{fileName}` only: the server reads `{merchantId}/{storeId}/imports/{fileName}` from its own bucket (BR-CAT-16); a `path` field is ignored. Synchronous: allow ~60 s (oms-web does). A retry after a timeout may say "SKU code in use" for an import that succeeded) |
| POST | `/stores/{storeId}/products/import-uploads` (BR-CAT-17): body `{sizeBytes}`, the exact size of the file, a whole number; 200 `{fileName, uploadUrl, method: "PUT", headers, expiresAt, maxBytes}`, `Cache-Control: no-store`; 400 size missing, not whole, below 1 or above 5 MB; 404 merchant, or store not the merchant's. The client PUTs the file **straight to S3** (`uploadUrl`, exactly `headers`, before `expiresAt`, 15 min) into `{merchantId}/{storeId}/imports/{fileName}`; S3 rejects another size, type, tag or key, or an expired URL (403). Then it calls the import with `fileName`. Uploaded files are deleted after 7 days. The bucket allows browser PUTs from the web origins only (`development` bucket CORS) |
| GET | `/stores/{storeId}/products/{productId}`, `/stores/{storeId}/products/search` (optional `notInCollectionId` leaves out that collection's products, 404 if it is not a collection of the store; order `sortBy` ∈ createdAt (default, DESC) / updatedAt / name / id, always `id` last; other `sortBy` or `direction` → 400; `direction` without `sortBy` applies to `createdAt`; `pageNumber` < 0 or `pageSize` < 1 → 400) |
| POST | `/stores/{storeId}/collections`, `.../{collectionId}/add-products`, `.../{collectionId}/remove-products` (add/remove are idempotent, BR-CAT-15: 200 with the collection as stored — a product already in / not in the collection is skipped (was 422); 400 missing or null id; 404 store, collection, or (add) a product not in the store; 409 changed by another request at the same moment (retry); 422 empty list) |
| GET | `/stores/{storeId}/collections`, `/stores/{storeId}/collections/{collectionId}`, `.../{collectionId}/products` (paged previews A→Z by name, `pageSize` 1–100) |

## REST — inventory-service (`:8058`, prefix `/v1/inventory`, no merchant in path yet)

| Method | Path | Visibility |
|--------|------|------------|
| POST | `/internal/v1/inventory/inventories` (create for a product's SKUs) | Internal only (`@Hidden`, blocked at gateway); kept for support. Rows it creates are **INACTIVE** (not orderable, BR-INV-08) until the catalog's next `ProductUpdated` sets their status — only when the request's `productId` is the product that owns the SKU in the catalog (otherwise the row stays INACTIVE); `ProductCreated` never changes an existing row, so to make such a row sellable, change the product in stores-service (decided 2026-11-06) |
| POST | `/v1/inventory/inventories/{inventoryId}` (adjust stock; the hold types `RESERVE`, `RESERVE_RELEASE`, `RESERVE_EXPIRE` are refused with 400, BR-INV-05; oms-web offers only the on-hand types) | Public |
| GET | `/v1/inventory/inventories/{inventoryId}`, `/v1/inventory/inventories/products/{productId}` | Public |
| GET | `/v1/inventory/inventories/stock-movements/{inventoryId}` | Public |

## Planned synchronous calls (Cart + Order MVP, ADR 0007)

| From | To | Call | Purpose |
|------|----|------|---------|
| order-service | stores-service | `POST /internal/v1/store/merchants/{merchantId}/stores/{storeId}/order-quote` (**built**; called by order-service's checkout intake) | Store status, merchant status, open now, SKU prices at placement and for a delivery quote; read-only, with `X-Request-Id`. Details below |
| cart-service | order-service | `POST /internal/v1/order/customers/{customerId}/checkouts/by-key/expire` (planned) | Unlock a stuck checkout: idempotent, inserts `EXPIRED` or returns the stored outcome |
| oms-web | order-service | `POST /v1/order/customers/{customerId}/delivery-quotes` (planned) | Delivery fee per store before checkout (BR-PRC-03) |

**`order-quote`** (stores-service `OrderQuoteInternalController`, `@Hidden`; no authentication for `/internal/**` yet, open question 65):
- **Request** `{ "skus": [...] }`: 0..100 codes (the `PlaceCheckout` line limit); 0 = store data only (delivery quote).
- **Response**: `store` {`id`, `code`, `name`, `status`, `address` (nullable, every field nullable), `timeZone`, `currency`,
  `autoAcceptOrder`, `allowPreOrder`, `maxOrdersPerDay`, `preparationTimeMinutes`}, `merchantStatus`, `now`, `localDate`
  (the store's date at `now`, for the daily cap and the order number; null when the time zone cannot be read), `open`,
  `reasons` (`STORE_NOT_ACTIVE`, `OUTSIDE_HOURS`, `CLOSED_WINDOW`, `INVALID_SCHEDULE`; all that apply), `closedWindowTypes`,
  `skus` [{`sku`, `found`, `productId`, `productName`, `skuName`, `price`, `currency`, `status`, `productStatus`}] — one per
  distinct code in request order, matched exactly; unknown, removed, null, blank, longer than 100 characters or containing NUL (`\u0000`) → `found: false`.
- **Advisory, raw**: statuses and currencies are not filtered; order-service applies BR-ORD-02 and maps them to
  `CheckoutRejected` codes (🟢 2026-11-15, user): `STORE_NOT_ACTIVE` → `STORE_INACTIVE`; `OUTSIDE_HOURS`,
  `CLOSED_WINDOW` and `INVALID_SCHEDULE` → `STORE_CLOSED` (BR-STO-04); `merchantStatus: SUSPENDED` → `MERCHANT_SUSPENDED`.
  Several reasons → **one entry per distinct code** for that store (e.g. a closed store outside its hours gets
  `STORE_INACTIVE` and `STORE_CLOSED`). Not a reservation: a store or price may change right after it.
- **Answers**: 200; 400 for no list, more than 100 codes or a path id that is not a UUID (a caller bug); 404 when the
  merchant does not exist or the store is not the merchant's — **final**: stores are never deleted, so the command carried
  a wrong merchant/store pair; reject that store with `INVALID_REQUEST` (🟢 2026-11-15, user), do not retry, alert; 5xx or a timeout
  → `STORE_UNAVAILABLE` (retry is the caller's choice).
- **Callers and volume**: order-service once per store per checkout and per delivery quote (estimate: below 10 calls per
  second in the MVP). Each call is 4 queries (merchant, store with its graph, windows, SKUs); all use an index except the
  store's business hours, read through the graph with no index on `store_business_hours.store_id` (open question 66). A
  store with an unreadable schedule logs one WARN per call.

## Front-end consumers

The exact list of calls oms-web makes, each matched to its endpoint, is generated: `architecture/generated/oms-web.md`.
The table below says what depends on them.

| Consumer | Calls | Notes |
|----------|-------|-------|
| **oms-web** (React, repo [`oms-web`](https://github.com/domt97/oms-web)) — Seller Centre `/seller` | All stores-service endpoints above (merchant-scoped), inventory-service `GET …/products/{productId}`, `GET …/{inventoryId}`, `POST …/{inventoryId}` (adjust), `GET …/stock-movements/{inventoryId}` | Through a reverse proxy on `/v1/store/` and `/v1/inventory/`; every call sends `X-Request-Id`; both services keep it when it matches `^[A-Za-z0-9._-]{1,64}$` (else a new UUID), echo it in the response and log it as MDC `requestId`. The product edit form calls the update-product PUT with the `version` from GET and sends back every field it does not edit (full replace); on 409 it re-reads the product to tell a stale version from a SKU code clash. The create form applies the same limits (100 SKUs, 20 images, 5000-character description). The Excel import (every seller) checks the file (.xlsx, at most 5 MB), calls `POST …/products/import-uploads` with the file's exact size, PUTs the file **straight to file storage** with the presigned URL and exactly the returned headers (the only call that leaves the API origin: no proxy, no `X-Request-Id`; allowed by the bucket's CORS rule), and only after that upload succeeded calls `POST …/products/import` with `{fileName}` (BR-CAT-16/17) |
| **oms-web** — storefront `/` | Temporarily the same merchant-scoped reads (store detail, product search/detail) and the inventory read by product | Until the public catalog (BR-USR-05) exists; see open question 34. Changing these paths, adding auth or capping `pageSize` breaks the storefront. |
| **oms-web** — both | `GET …/products/{productId}`; and (Seller Centre only) `GET …/stock-movements/{inventoryId}`, which will also return the hold types `RESERVE`, `RESERVE_RELEASE`, `RESERVE_EXPIRE` (BR-INV-05) | A SKU without an inventory record is not orderable (BR-CAT-04), nor an INACTIVE one (BR-INV-08). A SKU missing from the response has no record; the endpoint answers 404 when the whole product has none, which oms-web (storefront and Seller Centre, one adapter) also reads as "no record": answering `[]` instead keeps working, any other status for "no record" breaks it. oms-web must ship the change that shows the hold types (and the BR-CAT-04 rule) before inventory writes them |

## Synchronous calls between services

| From | To | Port | Status |
|------|----|------|--------|
| stores-service | inventory-service | `InventoryServiceClient.checkItemDetail(List<ItemDetailCheck>)` | Interface only, no adapter |
| stores-service | promotion-service | `PromotionServiceClient` | Empty interface |
