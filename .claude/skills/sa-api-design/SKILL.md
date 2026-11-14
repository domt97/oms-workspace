---
name: sa-api-design
description: REST API rules for the OMS — paths, public vs internal, validation, errors, paging, idempotent writes, compatibility. Use when a change adds or changes an endpoint or a service-to-service call.
user-invocable: false
---
# REST API design

## Rules
1. **Resource paths**:
   - nouns, plural, nested by ownership (`/merchants/{merchantId}/stores/{storeId}/products/{productId}`);
   - IDs are UUIDs in the path;
   - keep the service prefix (`/v1/store/...`, `/v1/inventory/...`).
   - Name non-CRUD state changes as action sub-resources (`/close`), and back each with a guarded domain transition.
2. **Public vs internal**:
   - Anything only another service calls goes under `/internal/v1/<service>/...`, `@Hidden`, and is never exposed by a future gateway.
   - Prefer events over synchronous calls for cross-service writes (workspace rule 2). A synchronous call is for reads that need a fresh answer. Commands between services (e.g. reserve stock at checkout) go through the sender's outbox as Kafka messages, with replies from the executor's outbox (ADR 0006), not through REST.
3. **Merchant in every public path** (or a verified token claim later). Every lookup is scoped by merchant, not by id alone (see `sa-multitenancy-security`).
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
   | missing | 404 (also when it exists but belongs to another merchant — don't leak existence) |
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
   - When one status has **several causes the client must handle differently**, give each a machine-readable `code` in
     the error body; clients must never parse the message. Example: update-product answers 409 for a stale version
     (client offers "reload") and for a SKU code used by another product (client keeps the edits). oms-core's
     `ErrorResponse` has no `code` yet, so oms-web re-reads the product and compares versions (known gap below).
10. **Full-replace `PUT` of an aggregate with child items** (e.g. update-product: product + SKUs + images):
    - Document the semantics: omitted optional fields are **cleared**; child items are matched by a natural key
      (SKU code) or id; items left out are removed (say whether soft or hard); the response carries the new `version`.
    - Make "nothing changed" cheap and safe: an identical body returns 200 with the current version without writing, so
      a client retry after a timeout is harmless.
    - **Clients** must send back every field they do not edit (or it is wiped) and keep untouched values exactly as
      loaded (no trimming, same order), and must map a re-entered key back to the stored item: "remove and add the same
      code again" in one edit is the same item, not a new one with blank fields. Test the round trip "loaded → untouched
      form → request" and expect the server's no-change answer.
11. **Service-to-service calls** are written behind an application port, with an adapter in `infrastructure` that sets:
    - a connect timeout and a read timeout;
    - retries **only** for idempotent calls;
    - a mapping of remote errors to domain exceptions.

    See `sa-resilience-observability`.

## Checklist
- [ ] Path, method, visibility (public/internal), merchant scoping.
- [ ] Request validation for every field and query param; what returns 400 vs 422 vs 409. Several causes behind one status → a machine-readable `code` per cause.
- [ ] Full-replace `PUT`: cleared fields, child matching key, removal semantics and no-change answer documented; client round-trip test planned.
- [ ] Idempotency on retry (same request twice → same result?).
- [ ] Paging/sorting bounds for lists.
- [ ] BREAKING? Who calls it today (`architecture/integration.md`, `generated/`)?
- [ ] OpenAPI annotations, `ErrorResponse` codes listed; controller test for mapping and status.
- [ ] Docs: `integration.md` (service-to-service), `domain-map.md` (new resource).

## Current state and known gaps
Not in this file. When you need how the OMS does this today, or which gaps are known, read
`.claude/skills/sa-api-design/references/current-state.md`. It is a snapshot: `architecture/generated/` and the code win.
