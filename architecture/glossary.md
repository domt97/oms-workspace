# Glossary

| Term | Meaning |
|------|---------|
| Merchant | A seller company on the platform, often a chain; owns one or more stores. Isolated from other merchants. Registers itself (unique case-insensitive code of letters and digits, ACTIVE on registration). Owned by stores-service: table `merchants`, `MerchantId`; other services carry `merchant_id`. |
| Tenant | Former name of **merchant** in code (renamed 2026-10). Do not use it in new designs. |
| Store | A branch of a merchant; has config, address, business hours, availability windows, its own catalog and stock. |
| Customer | A platform user; one account buys from every merchant. |
| Checkout | One customer action that turns a cart into one order per store, with one payment. |
| Store product | A product owned by a store (own catalog), status `DRAFT/ACTIVE/INACTIVE`. |
| SKU | Sellable variant of a store product (price, dimensions). Inventory is tracked per (store, SKU). |
| Collection | Merchandising group of products inside a store. |
| Store availability | Forced open/close window overriding business hours. |
| Inventory | Stock record for one SKU in one store: `quantity`, `reserved_quantity`, `available`. |
| Reservation | Temporary hold of stock for one order item (TTL 15 min) until confirmed (sold, at order `PLACED`), released or expired; a confirmed reservation becomes `RETURNED` when a cancelled order puts the goods back (`restock`). |
| Restock | Returning confirmed goods to stock when an order is cancelled and the goods can be sold again (BR-ORD-09); a `RETURN` movement. |
| Hold movement | Stock movement that changes only the reserved quantity: `RESERVE`, `RESERVE_RELEASE`, `RESERVE_EXPIRE` (BR-INV-05). |
| Command / reply | A request from one service to another (`ReserveStock`) sent through the sender's outbox, answered by an event from the executor's outbox (`StockReserved`); ADR 0006. |
| Order header (tombstone) | inventory's one row per order (`stock_reservation_orders`) that makes stock commands idempotent; a header closed before any reserve (tombstone) rejects late commands. |
| Stock movement | Immutable audit row for every stock change, linked to its cause by `reference_type` + `reference_id` (an order's movements: `ORDER_ITEM` + the order line, plus `reservation_id`; a manual adjustment: the reference the seller gives). |
| Outbox | `outbox_events` table written in the same transaction as the business change; Debezium streams it to Kafka. |
| ACL | Anti-corruption layer: external event DTOs in `infrastructure/message/dto`, mapped to internal commands. |
| Shared kernel | `oms-core`: types shared by all contexts. |
