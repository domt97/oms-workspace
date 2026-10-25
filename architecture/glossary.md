# Glossary

| Term | Meaning |
|------|---------|
| Tenant | A merchant company on the SaaS platform. Every record belongs to one tenant — through its own `tenant_id` or through a tenant-scoped parent (e.g. a store). |
| Store | A shop of a tenant; has config, address, business hours, availability windows. |
| Store product | A product owned by a store (own catalog), status `DRAFT/ACTIVE/INACTIVE`. |
| SKU | Sellable variant of a store product (price, dimensions). Inventory is tracked per (store, SKU). |
| Collection | Merchandising group of products inside a store. |
| Store availability | Forced open/close window overriding business hours. |
| Inventory | Stock record for one SKU in one store: `quantity`, `reserved_quantity`, `available`. |
| Reservation | Temporary hold of stock for one order item until confirmed, released or expired. |
| Stock movement | Immutable audit row for every stock change, linked to its cause by `reference_type` + `reference_id`. |
| Outbox | `outbox_events` table written in the same transaction as the business change; Debezium streams it to Kafka. |
| ACL | Anti-corruption layer: external event DTOs in `infrastructure/message/dto`, mapped to internal commands. |
| Shared kernel | `oms-core`: types shared by all contexts. |
