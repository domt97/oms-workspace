# Integration Catalog

Every way services talk to each other. Generated contracts (OpenAPI, event schemas) go in
`architecture/contracts/`; this file is the human-readable index.

## Events

Topic naming (ADR 0002): **topic = `event_type`** (e.g. `ProductCreated`), key = `aggregate_id`.
Connector `postgres-cdc` on Kafka Connect `:9084` reads `store.outbox_events` with
`EventRouter` + `route.topic.replacement=${routedByValue}`.

| Event | Producer | Transport | Consumer | Payload | Status |
|-------|----------|-----------|----------|---------|--------|
| `ProductCreated` | stores-service (`OutboxEventHelper`, on create + import) | Outbox → Debezium `EventRouter` → Kafka | inventory-service `ProductCreatedConsumer` (group `product-consumer`, topic `ProductCreated`) | `eventId, eventType, occurredAt, tenantId, storeId, productId, skus[]`; key = `aggregate_id` (productId) | Live |
| `OrderCreated` | order-service (not built) | Kafka | inventory-service `OrderCreatedEventConsumer` (group `order-consumer`) | not defined | Listener commented out |
| Reservation-expire tick | EventBridge rule `rate(1 minute)` | SQS `<profile>-reservation-expire-queue` | inventory-service `SqsReservationExpireConsumer` | ignored (trigger only) | Live |

Payload contract for `ProductCreated` is duplicated: `stores-service/.../domain/event/ProductCreatedEvent`
and `inventory-service/.../infrastructure/message/dto/ProductCreatedEvent`. Change both together.
The consumer double-decodes the value (JSON string inside JSON) because of the Connect JSON converter.

## REST — stores-service (`:8048`, prefix `/v1/tenants/{tenantId}`)

| Method | Path |
|--------|------|
| POST | `/stores` |
| GET | `/stores/{id}` |
| PUT | `/stores/{id}/close`, `/stores/{id}/reopen` |
| POST | `/stores/{id}/availability`, `/stores/{id}/availability/{availabilityId}/cancel` |
| PUT | `/stores/{storeId}/business-hours`, `/stores/{storeId}/configs` |
| POST | `/stores/{storeId}/products`, `/stores/{storeId}/products/import` |
| GET | `/stores/{storeId}/products/{productId}`, `/stores/{storeId}/products/search` |
| POST | `/stores/{storeId}/collections`, `.../{collectionId}/add-products`, `.../{collectionId}/remove-products` |
| GET | `/stores/{storeId}/collections`, `/stores/{storeId}/collections/{collectionId}` |

## REST — inventory-service (`:8058`, prefix `/v1`, no tenant in path)

| Method | Path |
|--------|------|
| POST | `/inventories` (create for a product's SKUs) |
| POST | `/inventories/{inventoryId}` (adjust stock) |
| GET | `/inventories/{inventoryId}`, `/inventories/products/{productId}` |
| GET | `/inventories/stock-movement/{inventoryId}` |

## Synchronous calls between services

| From | To | Port | Status |
|------|----|------|--------|
| stores-service | inventory-service | `InventoryServiceClient.checkItemDetail(List<ItemDetailCheck>)` | Interface only, no adapter |
| stores-service | promotion-service | `PromotionServiceClient` | Empty interface |
