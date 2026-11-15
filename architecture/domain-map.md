# Domain Map

Ownership of every concept in the OMS. If a feature touches a concept, the owning service is
where the change starts. Source of truth is the code in `repos/`; update this file when it changes.

## Store context — `stores-service`

**Owns:** merchants (seller self-registration), their stores and own product catalog.

| Aggregate | Holds | Tables |
|-----------|-------|--------|
| `Merchant` | seller company: `code` (letters and digits, unique, case-insensitive), `name`, status (`ACTIVE`, `SUSPENDED`) | `merchants` |
| `Store` | belongs to a merchant (`merchant_id` FK); status (`ACTIVE`, `INACTIVE`, `SUSPENDED`, `CLOSED`), `StoreConfig`, `Address`, `BusinessHour[]` | `stores`, `store_addresses`, `store_configs`, `store_business_hours` |
| `StoreAvailability` | forced open/close windows | `store_availability` |
| `StoreProduct` | product (`DRAFT`, `ACTIVE`, `INACTIVE`), `ProductSku[]` (price, dimensions), `ProductImage[]` | `store_products`, `product_skus`, `product_images` |
| `StoreCollection` | merchandising group, list of `ProductId` | `store_collections`, `product_collections` |
| Outbox | `ProductCreated` / `ProductUpdated`; `id` = payload `eventId`, JSONB `payload` and `correlation_context`; rows inserted and deleted in the same transaction, so the table is always empty and Debezium publishes from the WAL; `store.debezium_heartbeat` is a table of the connector setup (no merchant data, not Flyway) | `outbox_events` |

**Publishes:** `ProductCreated` (on create and on Excel import, `version` 0) and `ProductUpdated` (update-product PUT). Tables: `store_products.version`, `product_skus.store_id` / `removed_at`, `UNIQUE (store_id, sku)`.
**Consumes:** nothing yet.
**Internal API:** `POST /internal/v1/store/merchants/{merchantId}/stores/{storeId}/order-quote` for order-service (read-only: store, merchant status, open now from `Store.openAt`, SKU prices; `integration.md` → *Planned synchronous calls*).
**Outbound ports (not implemented yet):** `InventoryServiceClient.checkItemDetail`, `PromotionServiceClient`.
**Other storage:** S3: product import files in the configured bucket at `{merchantId}/{storeId}/imports/` (BR-CAT-16); the service signs presigned PUTs and the oms-web Seller Centre uploads the files straight to S3 (BR-CAT-17; real-environment setup: open question 57). Product images are URLs, not stored by the service.

## Inventory context — `inventory-service`

**Owns:** stock truth per (store, SKU).

| Aggregate | Holds | Tables |
|-----------|-------|--------|
| `Inventory` | `quantity`, `reservedQuantity`, `available = quantity − reserved`, status (`ACTIVE`, `INACTIVE`); unique (store_id, sku) | `inventories` |
| `StockReservation` | hold for one order item, `expires_at`, status (`RESERVED`, `CONFIRMED`, `RELEASED`, `EXPIRED`, `RETURNED`; `CANCELLED` unused, BR-INV-03); `UNIQUE (order_id, order_item_id)` (V4) | `stock_reservations` |
| `StockReservationOrder` — order header *(ADR 0006, V4)* | one row per order: `merchant_id`, `store_id`, status (`RESERVED`, `REJECTED` with the stored reasons in JSONB `rejection`, `CONFIRMED`, `CANCELLED` = closed), `restock` (set by the first release); idempotency and out-of-order commands | `stock_reservation_orders` |
| Outbox *(ADR 0006, V5)* | the stock replies; `id` = payload `eventId`, `merchant_id`, `aggregate_id` = orderId, JSONB `payload` and `correlation_context`; rows inserted and deleted in the same transaction, so the table is always empty (Debezium reads the WAL) | `outbox_events` |
| `ProductCatalogVersion` | last applied catalog event version per product (`product_id`, `merchant_id`, `store_id`, `version`); ordering gate for `ProductCreated`/`ProductUpdated` | `product_catalog_versions` |
| `StockMovement` | append-only audit; type `RECEIVE`, `SALE`, `RETURN`, `ADJUSTMENT_IN/OUT`, `DAMAGE`, `TRANSFER_IN/OUT`, and the hold types `RESERVE`, `RESERVE_RELEASE`, `RESERVE_EXPIRE` (BR-INV-05); polymorphic `reference_type` + `reference_id`: movements of an order reference the order line (`ORDER_ITEM` + order item id) and carry `reservation_id` (unique per reservation and type, V4) | `stock_movements` |

**Consumes:** `ProductCreated` and `ProductUpdated` (Kafka) → create missing SKUs and set inventory status, through a per-product version gate (`product_catalog_versions`); failures to `<topic>.DLT`; reservation-expire tick (EventBridge → SQS) → expires overdue reservations; the stock commands `ReserveStock`, `ConfirmStockReservation`, `ReleaseStockReservation` (Kafka, ADR 0006; `ReserveStockConsumer`, `ConfirmStockReservationConsumer`, `ReleaseStockReservationConsumer`; failures to `<topic>.DLT`; no producer until order-service is built).
**Publishes:** the stock replies through `outbox_events` (V5; rows inserted and deleted in the same transaction, published by Debezium from the WAL; connector `inventory-outbox-cdc`): `StockReserved`, `StockReservationRejected`, `StockReservationConfirmed`, `StockReservationConfirmationFailed`, `StockReservationReleased`, `StockReservationExpired`. Also in DB `inventory`, owned by the connector setup and not by Flyway: table `debezium_heartbeat` (heartbeat rows only, no merchant data).

## Shared kernel — `oms-core`

Typed IDs: `MerchantId`, `StoreId`, `ProductId`, `SKU`, `InventoryId`, `OrderId`, `OrderItemId`,
`CustomerId`, `CategoryId`, `ReferenceId`, `EventId`. Value objects: `Money`, `Address`, `PriceRange`.
Base: `AggregateRoot`, `BaseDomain`, `PagedResult`. Exceptions: `BusinessException`,
`NotFoundException`, `ValidationException`. Infra: S3, Excel import template,
request logging, Swagger config.

Note: `OrderId`, `OrderItemId`, `CustomerId` already exist here, ahead of the order context.

## Planned contexts

Full target picture (subdomains, context map, roadmap): `vision.md`.

| Context | Expected responsibility | Evidence in code |
|---------|------------------------|------------------|
| Cart (`cart-service`, planned, DB `cart`) | One cart per customer across stores; checkout sends `PlaceCheckout` (ADR 0007) | none yet |
| Order (`order-service`, planned, DB `orders`) | Checkout placement and the order saga: one order per store, line snapshots, stock commands (ADR 0006), accept/reject, mock delivery partner, COD reconciliation (ADR 0007) | inventory's stock command consumers (ADR 0006), `OrderId` in oms-core |
| Promotion (`promotion-service`) | Pricing rules / discounts | Empty `PromotionServiceClient` |
