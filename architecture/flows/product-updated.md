# Flow: Product updated → inventory kept in sync

Status: **planned** (update-product). Decisions U1–U11 recorded 2026-10-28 (`business-rules.md` BR-CAT-08..12, BR-INV-08..10; U8 currency revised the same day, BR-STO-03).

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
    S->>S: StoreProduct.replace(...) → change set (empty → 200 with the current version, nothing written, no event — even if the sent version is stale)
    S->>PG: UPDATE store_products SET version = v+1 WHERE id, store_id, version = v (0 rows → 409)
    S->>PG: check SKU codes against other products of the store (→ 409), apply SKU/image diff, flush
    S->>PG: INSERT outbox_events(ProductUpdated, version v+1) — same transaction
    S-->>M: 200 {version v+1}
    PG-->>D: WAL change on outbox_events
    D->>K: topic ProductUpdated, key = productId
    K->>I: ProductUpdatedConsumer (group inventory-product-updated)
    I->>IPG: tx: version gate FIRST: upsert product_catalog_versions WHERE version < v+1 (0 rows → stale/duplicate, skip); its row lock serialises all work on this product
    I->>IPG: load inventories by (store, product); merchant mismatch → WARN, roll back (gate included)
    I->>IPG: create inventory for new SKUs (ON CONFLICT DO NOTHING)
    I->>IPG: re-read rows, guarded status UPDATE by (store_id, store_product_id, sku) over the whole snapshot, in inventory-id order
```

## Rules applied

- **Stale version, same content:** the change set is computed before the version check, so a retried PUT whose content is already applied returns 200 with the current version (safe client retry). Stale version with different content → 409.
- **SKU code uniqueness:** until `UNIQUE (store_id, sku)` ships (second release), the "code used by another product → 409" rule is only a check before writing; two concurrent writes on different products of the same store can both succeed.
- **SKU identity = code.** A body SKU whose code exists on the product updates that row (id kept); a new code is added; an existing code missing from the body is soft-removed; a removed code that comes back revives the same row. A removed code stays reserved in the store (another product → 409).
- **Product status:** DRAFT → ACTIVE / INACTIVE, ACTIVE ↔ INACTIVE, never back to DRAFT; ACTIVE needs at least one ACTIVE SKU (422).
- **Inventory status = orderable:** ACTIVE only when the product is ACTIVE, the SKU is ACTIVE and not removed; otherwise INACTIVE. Inventory rows are **never deleted** (reservations and movements have no FK to them; stock on hand would be lost).
- Open reservations are kept when a SKU or product is deactivated; stock can still be adjusted on an INACTIVE inventory.

## Ordering and idempotency

- `ProductCreated` (version 0) and `ProductUpdated` (version ≥ 1) are different topics and consumer groups, so Kafka does not order them and they can run at the same time. The gate statement runs first in each transaction, so the second one waits on the gate row lock and then loads the rows the first one committed. The per-product gate (`product_catalog_versions`) applies an event only if its version is newer; a late `ProductCreated` cannot re-create a removed SKU, and a lost `ProductCreated` is repaired by the first `ProductUpdated`.
- Idempotency key: `(productId, version)`. Redelivery and DLT replay are no-ops.

## Code entry points (planned)

- `stores-service`: `UpdateStoreProductService`, `StoreProduct.replace`, `OutboxEventHelper.createProductUpdatedOutboxEvent`
- `inventory-service`: `ProductUpdatedConsumer` → `SyncProductInventoryService`; `ProductCreated` path also goes through the gate

## Things to watch

- The payload is defined in `contracts/events/ProductUpdated.schema.json`; both services' DTOs must follow it.
- SKU codes are up to 100 characters in stores-service but `inventories.sku` is `VARCHAR(50)` (open question 41): widen it in the same inventory migration as the gate table, before this consumer goes live.
- Until the dead-letter topic exists (open question 17), a skipped event leaves a removed SKU ACTIVE in inventory.
