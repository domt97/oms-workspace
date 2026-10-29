# Flow: Product created → inventory initialised

Status: **live**.

```mermaid
sequenceDiagram
    actor M as Merchant
    participant S as stores-service
    participant PG as Postgres (store)
    participant D as Debezium (Kafka Connect)
    participant K as Kafka
    participant I as inventory-service
    participant IPG as Postgres (inventory)

    M->>S: POST /v1/store/merchants/{merchantId}/stores/{storeId}/products (or /products/import)
    S->>PG: tx: insert store_products + product_skus + outbox_events(ProductCreated)
    PG-->>D: WAL change on outbox_events
    D->>K: EventRouter, route by event_type, key = productId
    K->>I: ProductCreatedConsumer (group product-consumer)
    I->>IPG: SyncProductInventoryService: version gate (0), one inventory row per SKU (quantity 0)
```

## Code entry points

- `stores-service`: `CreateStoreProductUseCaseService`, `ImportProductService`, `OutboxEventHelper`, `OutboxEventPersistenceAdapter`
- `inventory-service`: `ProductCreatedConsumer` → `SyncProductInventoryService`

## Things to watch when changing this flow

- Payload class exists in both services — keep them in sync.
- Delivery is at-least-once; `inventories` has unique (store_id, sku), so duplicates must be handled gracefully.
- Later changes (SKU added/removed, price, deactivation) travel as `ProductUpdated` ([product-updated.md](product-updated.md)). `ProductCreated` carries `version` 0 and goes through inventory's per-product version gate (`SyncProductInventoryService`), so a late `ProductCreated` is a no-op; failures go to `ProductCreated.DLT`.
