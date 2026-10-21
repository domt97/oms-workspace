# Open Questions & Doc/Code Drift

Resolve each item, then delete it or turn it into an ADR. Last reviewed 2026-10-21. Items 1–3 (README drift, topic naming) resolved: stores-service#35, inventory-service#17, ADR 0002.

## Local infrastructure

4. Debezium connector registration is not scripted in `development` (only documented in the stores README).
5. `development/docker/docker-compose.yml` mounts `./postgres/init` for Postgres, but the folder is not in the repo (DB/schema creation).

## Correctness (inventory-service)

13. `ReserveStockService` is **not idempotent per order item** — replay reserves twice. Needs a uniqueness rule on (order_item_id, inventory_id) or a check.
14. Reserve / confirm / expire do **not write `StockMovement`** — audit trail incomplete.
15. **Race: confirm vs expire on the same reservation → oversell risk.** Both load the reservation as `RESERVED` and save the new status via load-modify-save (`StockReservationRepositoryAdapter.updateBatch`) with no `WHERE status = 'RESERVED'` and no `@Version`. If both run, `reserved_quantity` is decremented twice → available stock inflated. Fix: guarded status transition (`UPDATE … WHERE id = :id AND status = 'RESERVED'`), treat 0 rows as "handled by the other side".
16. **Expiry run aborts on the first failure.** `ExpireStockReservationService` only catches `ObjectOptimisticLockingFailureException`, which can never be thrown (no `@Version`). Any other exception (e.g. `InvalidReservationException` when release updates 0 rows) stops the remaining inventories of that run.

## Reliability (messaging)

17. Kafka consumers have **no dead-letter topic / custom error handler**: spring-kafka default retries 10 times with no backoff, then skips the record — a failing message is silently lost.
18. SQS `reservation-expire` queue has **no DLQ / redrive policy** (`development/docker/infra/local/main.tf`).
19. **`outbox_events` is never cleaned up**: rows stay `PENDING` forever; no job deletes published rows.

## Code hygiene

20. `oms-core/.../domain/page/PagedResult.java` imports Spring Data `Page` — the only framework dependency inside a `domain` package.

## Design decisions pending (decide when a feature needs them)

6. inventory-service REST has **no `tenantId`** in path or header, unlike stores-service.
7. `InventoryServiceClient` (stores → inventory) and `PromotionServiceClient` have no adapter.
8. `ReleaseStockReservationUseCase` has no implementation; reserve/confirm have no entry points.
9. Only `ProductCreated` is published — no event for product/SKU update, deactivation, or store close.
10. `ProductCreatedEvent` is duplicated in both services; no shared schema / schema-registry subject.
11. Consumer group `product-consumer` is a generic name; may collide when more services consume products.
