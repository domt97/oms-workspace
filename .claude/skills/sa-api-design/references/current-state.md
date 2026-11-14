# REST API design — how the OMS does it today (snapshot)

Moved out of `SKILL.md` so the rules load without it. This is a hand-written snapshot, not a rule: before relying on
a line, check it against `architecture/generated/<service>.md` and the code — code wins. A gap listed here without an
open-question number is not yet in `architecture/open-questions.md`.

## OMS today (verified in code)
**Paths**
- stores-service: `/v1/store/merchants/{merchantId}/stores/{storeId}/...` (controllers under `infrastructure/rest/api`, class-level `@RequestMapping("/v1/store")`).
- inventory-service public: `/v1/inventory/inventories/...`, **without `merchantId`** (open question 6). Internal: `/internal/v1/inventory/inventories` (`InventoryInternalController`, `@Hidden`).
- Prefix convention: `/v<major>/<service>/...` for public APIs and `/internal/v<major>/<service>/...` for service-to-service calls. `architecture/generated/<service>.md` lists every endpoint with its visibility.

**Validation and errors**
- Request DTOs use Jakarta validation with `@Valid`. Exception: `ImportStoreProductsRequest` (`POST .../products/import`) has **no `@Valid` and no constraints**.
- Errors use `oms-core` `GlobalExceptionHandler` (`oms-core/.../rest/GlobalExceptionHandler.java`). Body is `ErrorResponse {error, errors[], status, timestamp, path}`.

  | Exception | Status |
  |-----------|--------|
  | `NotFoundException` | 404 |
  | `ValidationException` and bean validation | 400 (bean validation lists `field: message`) |
  | `BusinessException` | 422 |
  | anything else | 500 `Internal Server Error` (message hidden) |

  Services extend the handler: `StoreExceptionHandler`, `InventoryExceptionHandler`.
- Bad paging input becomes **500, not 400** on endpoints that use `PageUtils.toPageRequest` directly: an unknown `sortBy` or `direction` throws from Spring Data or `Sort.Direction.valueOf`, which the catch-all maps to 500. stores-service product search and collection products check paging in the controller (`RestPaging`) and allow-list `sortBy` (`StoreProductPersistenceAdapter.toSearchPageRequest`) → 400; follow that pattern.

**Paging and responses**
- Paging: `pageNumber`/`pageSize`/`sortBy`/`direction` query params mapped to `DomainPageRequest`. Response is `PagedResult<T>` (`oms-core/.../domain/page/PagedResult.java`). Max page size only on collection products (100); product search has none because the storefront depends on it (`integration.md` → Front-end consumers).

**Write semantics**
- Store state changes use action sub-resources: `PUT .../stores/{storeId}/close`, `PUT .../reopen`, `POST .../availability/{storeAvailabilityId}/cancel`, `POST .../collections/{collectionId}/add-products`. Name path variables `<thing>Id` (not `{id}`): the MDC defaults in oms-core `app.logging.mdc.fields` cover the common ones; others are added per service in `application.yaml`.
- Stock adjustment is `POST /v1/inventory/inventories/{inventoryId}`. It is not idempotent and has no idempotency key; a retried request adjusts twice.

**Documentation and clients**
- OpenAPI via springdoc 2.3.0 (`/swagger-ui.html`, `@Operation`/`@ApiResponses` on every public endpoint). Internal endpoints are `@Hidden`.
- Service-to-service: `InventoryServiceClient` and `PromotionServiceClient` are ports without adapters. No HTTP client library is on the classpath yet.

## Known gaps
- inventory public API has no merchant in the path (open question 6); reads are by id only.
- Import request not validated; invalid `sortBy`/`direction` → 500 outside product search; no max page size on product search.
- No idempotency key on stock adjustment.
- No HTTP client adapters, timeouts or retry policy defined for service-to-service calls.
- `ErrorResponse` (oms-core) has no machine-readable `code`; stores-service update-product's two kinds of 409 differ only by message.
