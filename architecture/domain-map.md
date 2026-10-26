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
| Outbox | pending integration events | `outbox_events` |

**Publishes:** `ProductCreated` (on create and on Excel import).
**Consumes:** nothing yet.
**Outbound ports (not implemented yet):** `InventoryServiceClient.checkItemDetail`, `PromotionServiceClient`.
**Other storage:** S3 (product import files / images).

## Inventory context — `inventory-service`

**Owns:** stock truth per (store, SKU).

| Aggregate | Holds | Tables |
|-----------|-------|--------|
| `Inventory` | `quantity`, `reservedQuantity`, `available = quantity − reserved`, status (`ACTIVE`, `INACTIVE`); unique (store_id, sku) | `inventories` |
| `StockReservation` | hold for one order item, `expires_at`, status (`RESERVED`, `CONFIRMED`, `RELEASED`, `EXPIRED`, `CANCELLED`) | `stock_reservations` |
| `StockMovement` | append-only audit; type `RECEIVE`, `SALE`, `RETURN`, `ADJUSTMENT_IN/OUT`, `DAMAGE`, `TRANSFER_IN/OUT`; polymorphic `reference_type` + `reference_id` | `stock_movements` |

**Consumes:** `ProductCreated` (Kafka) → creates inventory rows; reservation-expire tick (EventBridge → SQS) → expires overdue reservations; `OrderCreated` (consumer stub, disabled).
**Publishes:** nothing yet.
**Use cases without an entry point yet:** `ReserveStock`, `ConfirmStockReservation`, `ReleaseStockReservation` (interface only).

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
| Order (`order-service`) | Order lifecycle; publishes `OrderCreated`, order confirmed/cancelled | Disabled `OrderCreatedEventConsumer`, `OrderId` in oms-core |
| Promotion (`promotion-service`) | Pricing rules / discounts | Empty `PromotionServiceClient` |
