# Open Questions & Doc/Code Drift

Found while building this workspace (2026-10-18). Resolve each item, then delete it or turn it into an ADR.

## Drift between README and code (code wins)

1. **Reservation statuses** — inventory README says `PENDING → CONFIRMED | EXPIRED`; code `ReservationStatus` has `RESERVED, CONFIRMED, RELEASED, EXPIRED, CANCELLED`.
2. **Stock movement endpoint** — README `GET /v1/stock-movements`; code `GET /v1/inventories/stock-movement/{inventoryId}`.
3. **Kafka topic name** — stores README says topic `store.outbox_events`; consumer listens on `ProductCreated`. With Debezium `EventRouter` routing by `event_type`, the default topic is `outbox.event.<event_type>` unless `route.topic.replacement` is set. Confirm the real connector config.

## Gaps

4. Debezium connector registration JSON lives only in the stores README, not in `development` (no script registers it).
5. `development/docker/docker-compose.yml` mounts `./postgres/init` for Postgres, but the folder is not in the repo (DB/schema/debezium user creation).
6. inventory-service REST has **no `tenantId`** in path or header, unlike stores-service — tenant isolation for these endpoints is unclear.
7. `InventoryServiceClient` (stores → inventory) and `PromotionServiceClient` have no adapter.
8. `ReleaseStockReservationUseCase` has no implementation; reserve/confirm have no entry points.
9. Only `ProductCreated` is published — no event for product/SKU update, deactivation, or store close. Inventory cannot react to those.
10. `ProductCreatedEvent` is duplicated in both services; no shared schema or schema-registry subject, although Schema Registry runs locally.
11. inventory-service consumer group for products is `product-consumer` (generic name; may collide when more services consume products).
