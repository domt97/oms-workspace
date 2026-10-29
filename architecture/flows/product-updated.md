# Flow: Product updated → inventory kept in sync

Status: **built** — stores-service#48 (PUT + `ProductUpdated`) and inventory-service#32 (consumer); live once both are merged into `develop` (inventory first). Decisions U1–U11 recorded 2026-10-28 (`business-rules.md` BR-CAT-08..12, BR-INV-08..10; U8 currency revised the same day, BR-STO-03).

```mermaid
sequenceDiagram
    actor M as Merchant (oms-web Seller Centre)
    participant S as stores-service
    participant PG as Postgres (store)
    participant D as Debezium (Kafka Connect)
    participant K as Kafka
    participant I as inventory-service
    participant IPG as Postgres (inventory)

    M->>S: GET product (response includes version v)
    M->>S: PUT /v1/store/merchants/{merchantId}/stores/{storeId}/products/{productId} {version v, ...}
    S->>PG: load merchant, store by (merchantId, storeId), product by (storeId, productId) — 404 otherwise
    S->>S: StoreProduct.replace(...) → change set (validates every SKU in the body; rule errors on a stale version → 409)
    S->>PG: empty change set → re-read the stored version (mixed read → 409), else 200 with the current version, nothing written, no event
    S->>PG: UPDATE store_products SET version = v+1, updated_at WHERE id, store_id, version = v (0 rows → 409; row lock until commit)
    S->>PG: SKU codes of other products of the store (→ 409), apply SKU/image changes in place, flush (uk_product_skus_store_sku → 409)
    S->>PG: INSERT outbox_events(ProductUpdated, version v+1, merchant of the store) — same transaction
    S-->>M: 200 {version v+1}
    PG-->>D: WAL change on outbox_events
    D->>K: topic ProductUpdated, key = productId
    K->>I: ProductUpdatedConsumer (group inventory-product-updated)
    I->>IPG: tx: version gate FIRST: upsert product_catalog_versions WHERE version < v+1 AND same merchant/store (0 rows → stale/duplicate: skip; other merchant/store: exception → DLT); its row lock serialises all work on this product
    I->>IPG: load the product's inventory rows by store_product_id; a row of another merchant or store → exception → DLT, nothing written (gate rolled back)
    I->>IPG: create inventory for new SKUs, sorted by code (ON CONFLICT DO NOTHING; a code owned by another product → WARN, skipped)
    I->>IPG: re-read the rows, guarded status UPDATE by (id, merchant, store, product) WHERE status <> target, in Java UUID order
```

## Rules applied

- **Stale version, same content:** the change set is computed before the version check, so a retried PUT whose content is already applied returns 200 with the current version (safe client retry). The stored version is re-read first, so a body that matches a mix of two versions (another update committed between the reads) gets 409. Stale version with different content → 409. A request still in flight when the retry arrives also gets 409 (the client re-reads).
- **SKU code uniqueness:** enforced by `UNIQUE (store_id, sku)` (`product_skus`, removed codes included); the app checks first for a clear 409, the constraint catches races (→ 409).
- **SKU identity = code** (case-sensitive). A body SKU whose code exists on the product updates that row (id kept); a new code is added; an existing code missing from the body is soft-removed (`removed_at`); a removed code that comes back revives the same row. A removed code stays reserved in the store (another product → 409).
- **Every SKU in the body passes the SKU price rule** (the `ProductUpdated` contract requires valid prices), so a stored SKU that breaks it must be corrected when the product is edited.
- **Product status:** DRAFT → ACTIVE / INACTIVE, ACTIVE ↔ INACTIVE, never back to DRAFT; ACTIVE needs at least one ACTIVE SKU (422).
- **Inventory status = orderable:** ACTIVE only when the product is ACTIVE, the SKU is ACTIVE and not removed; otherwise INACTIVE. Inventory rows are **never deleted** (reservations and movements have no FK to them; stock on hand would be lost).
- Open reservations are kept when a SKU or product is deactivated; stock can still be adjusted on an INACTIVE inventory.

## Ordering and idempotency

- `ProductCreated` (version 0) and `ProductUpdated` (version ≥ 1) are different topics and consumer groups, so Kafka does not order them and they can run at the same time. The gate statement runs first in each transaction, so the second one waits on the gate row lock and then loads the rows the first one committed. The per-product gate (`product_catalog_versions`) applies an event only if its version is newer; a late `ProductCreated` cannot re-create a removed SKU, and a lost `ProductCreated` is repaired by the first `ProductUpdated`.
- Idempotency key: `(productId, version)`. Redelivery is a no-op. Replaying a DLT record applies it only if its version is still newer than the last applied one (a record dead-lettered before it was applied is applied; an outdated one is skipped).
- Failures: contract errors and ownership mismatches go to `ProductUpdated.DLT` at once; database outages are retried until the database is back; other failures are retried 6 times (~35 s), then dead-lettered.

## Code entry points

- `stores-service`: `UpdateStoreProductService`, `StoreProduct.replace`, `StoreProductPersistenceAdapter.bumpVersion` / `applyChanges`, `OutboxEventHelper.createProductUpdatedOutboxEvent`
- `inventory-service`: `ProductUpdatedConsumer` → `SyncProductInventoryService`; `ProductCreatedConsumer` uses the same service (version 0); `KafkaErrorHandlingConfig` (DLT)

## Things to watch

- The payload is defined in `contracts/events/ProductUpdated.schema.json`; both services' DTOs must follow it. Adding an enum value (product or SKU status) is a breaking change for the inventory consumer.
- Removed SKU rows are kept and loaded on every update of the product (open question 43).
- DLT records have no alerting and no replay tool yet (open question 40).
