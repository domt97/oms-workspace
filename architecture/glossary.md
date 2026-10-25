# Glossary

| Term | Meaning |
|------|---------|
| Merchant | A seller company on the platform, often a chain; owns one or more stores. Isolated from other merchants. Code: `merchant_id`, `MerchantId`, DynamoDB `<profile>_merchant_info`. |
| Tenant | Former name of **merchant** in code (renamed 2026-10). Do not use it in new designs. |
| Store | A branch of a merchant; has config, address, business hours, availability windows, its own catalog and stock. |
| Customer | A platform user; one account buys from every merchant. |
| Checkout | One customer action that turns a cart into one order per store, with one payment. |
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
