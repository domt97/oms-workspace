---
name: sa-api-design
description: REST API design in the OMS — resource paths and versioning, public vs internal APIs, request validation, error format, status codes, pagination and sorting, idempotency of writes, backward compatibility and OpenAPI. Use when adding or changing a REST endpoint or a service-to-service call.
---
# REST API design

## OMS today (verified in code)
**Paths**
- stores-service: `/v1/store/tenants/{tenantId}/stores/{storeId}/...` (controllers under `infrastructure/rest/api`, class-level `@RequestMapping("/v1/store")`).
- inventory-service public: `/v1/inventory/inventories/...`, **without `tenantId`** (open question 6). Internal: `/internal/v1/inventory/inventories` (`InventoryInternalController`, `@Hidden`).
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
- Bad paging input becomes **500, not 400**: an unknown `sortBy` or `direction` throws from Spring Data or `Sort.Direction.valueOf` in `PageUtils`, which the catch-all maps to 500.

**Paging and responses**
- Paging: `pageNumber`/`pageSize`/`sortBy`/`direction` query params mapped to `DomainPageRequest`. Response is `PagedResult<T>` (`oms-core/.../domain/page/PagedResult.java`). There is no max page size.

**Write semantics**
- Store state changes use action sub-resources: `PUT .../stores/{id}/close`, `PUT .../reopen`, `POST .../availability/{id}/cancel`, `POST .../collections/{id}/add-products`.
- Stock adjustment is `POST /v1/inventory/inventories/{inventoryId}`. It is not idempotent and has no idempotency key; a retried request adjusts twice.

**Documentation and clients**
- OpenAPI via springdoc 2.3.0 (`/swagger-ui.html`, `@Operation`/`@ApiResponses` on every public endpoint). Internal endpoints are `@Hidden`.
- Service-to-service: `InventoryServiceClient` and `PromotionServiceClient` are ports without adapters. No HTTP client library is on the classpath yet.

## Rules
1. **Resource paths**:
   - nouns, plural, nested by ownership (`/tenants/{tenantId}/stores/{storeId}/products/{productId}`);
   - IDs are UUIDs in the path;
   - keep the service prefix (`/v1/store/...`, `/v1/inventory/...`).
   - Name non-CRUD state changes as action sub-resources (`/close`), and back each with a guarded domain transition.
2. **Public vs internal**:
   - Anything only another service calls goes under `/internal/v1/<service>/...`, `@Hidden`, and is never exposed by a future gateway.
   - Prefer events over synchronous calls for cross-service writes (workspace rule 2). A synchronous call is for reads that need a fresh answer, or for commands that need an immediate yes/no, e.g. reserve stock at checkout.
3. **Tenant in every public path** (or a verified token claim later). Every lookup is scoped by tenant, not by id alone (see `sa-multitenancy-security`).
4. **Validate at the edge**:
   - `@Valid` on every body, with constraints on every field;
   - bounds on query params (`@Max` page size, an allow-list for `sortBy`);
   - invalid input → 400, never 500.
   - Business rule violations come from the domain as `BusinessException` → 422.
5. **Status codes**:

   | Case | Status |
   |------|--------|
   | create | 201 (+ body or `Location`) |
   | read / update | 200 |
   | accepted async | 202 |
   | bad input | 400 |
   | missing | 404 (also when it exists but belongs to another tenant — don't leak existence) |
   | conflict / duplicate | 409 |
   | rule violation | 422 |

   Document them with `@ApiResponses`.
6. **Idempotent writes**:
   - `PUT` and action endpoints must be safe to repeat (guarded transitions: "already closed" → 200 or 409, decided and documented).
   - `POST` that creates or moves quantities accepts an `Idempotency-Key` header (or a natural key such as `orderItemId`), backed by a unique constraint.
7. **Paging**:
   - every list endpoint is paged with a max page size and an allow-listed sort;
   - use keyset/cursor paging for large or append-only collections (movements, orders).
8. **Compatibility**:
   - adding optional fields and new endpoints is non-breaking;
   - removing or renaming fields, changing types or semantics, making a field required, or changing status codes is **BREAKING**. A breaking change needs a new version (`/v2/...`) running alongside v1 until callers move.
   - Clients must ignore unknown fields.
9. **Errors**: always the `ErrorResponse` shape. Never return stack traces or SQL messages. Messages live in each service's `Constants`.
10. **Service-to-service calls** are written behind an application port, with an adapter in `infrastructure` that sets:
    - a connect timeout and a read timeout;
    - retries **only** for idempotent calls;
    - a mapping of remote errors to domain exceptions.

    See `sa-resilience-observability`.

## Checklist
- [ ] Path, method, visibility (public/internal), tenant scoping.
- [ ] Request validation for every field and query param; what returns 400 vs 422 vs 409.
- [ ] Idempotency on retry (same request twice → same result?).
- [ ] Paging/sorting bounds for lists.
- [ ] BREAKING? Who calls it today (`architecture/integration.md`, `generated/`)?
- [ ] OpenAPI annotations, `ErrorResponse` codes listed; controller test for mapping and status.
- [ ] Docs: `integration.md` (service-to-service), `domain-map.md` (new resource).

## Known gaps
- inventory public API has no tenant in the path (open question 6); reads are by id only.
- Import request not validated; invalid `sortBy`/`direction` → 500; no max page size.
- No idempotency key on stock adjustment.
- No HTTP client adapters, timeouts or retry policy defined for service-to-service calls.
