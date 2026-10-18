# Open Questions & Doc/Code Drift

Resolve each item, then delete it or turn it into an ADR. Last reviewed 2026-10-18.

## In review (PRs open)

1. ~~Reservation statuses / movement types in inventory README~~ — fixed in domt97/inventory-service#17.
2. ~~Stock movement endpoint in inventory README~~ — fixed in domt97/inventory-service#17.
3. ~~Debezium connector in stores README outdated~~ — fixed in domt97/stores-service#35. Topic naming: ADR 0002.

## Local infrastructure

4. Debezium connector registration is not scripted in `development` (only documented in the stores README).
5. `development/docker/docker-compose.yml` mounts `./postgres/init` for Postgres, but the folder is not in the repo (DB/schema creation).

## Correctness (inventory-service)

12. `ProductCreatedConsumer` is **not idempotent**: redelivery violates unique (store_id, sku) and the consumer throws (likely retried forever / blocks the partition).
13. `ReserveStockService` is **not idempotent per order item** — replay reserves twice. Needs a uniqueness rule on (order_item_id, inventory_id) or a check.
14. Reserve / confirm / expire do **not write `StockMovement`** — audit trail incomplete.

## Design decisions pending (decide when a feature needs them)

6. inventory-service REST has **no `tenantId`** in path or header, unlike stores-service.
7. `InventoryServiceClient` (stores → inventory) and `PromotionServiceClient` have no adapter.
8. `ReleaseStockReservationUseCase` has no implementation; reserve/confirm have no entry points.
9. Only `ProductCreated` is published — no event for product/SKU update, deactivation, or store close.
10. `ProductCreatedEvent` is duplicated in both services; no shared schema / schema-registry subject.
11. Consumer group `product-consumer` is a generic name; may collide when more services consume products.
