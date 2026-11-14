---
name: change-api
description: Steps to add or change a REST endpoint of an OMS service without breaking its callers, including oms-web. Use when a change adds, changes or removes an endpoint, its auth, paging or response fields.
---
# Add or change a REST endpoint

Rules: `sa-api-design`, `sa-multitenancy-security`; tests: `sa-testing-strategy`.

1. **Shape.** Public or internal path, merchant in the path, validation, status codes and error body, paging cap, and
   whether a repeated write is safe. Every lookup is scoped by merchant (system rule 4): another merchant's id gives 404
   and writes nothing.
2. **Who calls it.** Look the endpoint up in `architecture/integration.md`, including *Front-end consumers*, and grep the
   web adapters in `repos/oms-web/src/adapters/http/`. Ask `web-expert` what the web needs to change.
3. **Breaking or not.** A changed path, auth, paging cap or a removed or retyped response field is **BREAKING** for every
   caller found in step 2. Then do it in three steps: add the new form, move the callers, remove the old form — each its own PR.
4. **Implement** with `/ship <service> …`; a web change follows the same steps by hand in `repos/oms-web` (`npm run check`).
5. **Tests.** Validation and status codes at controller level, the cross-merchant case, and what a unit test cannot show
   (JSON mapping, SQL) by the means `sa-testing-strategy` names.
6. **Docs** (oms-workspace, same piece of work): `integration.md` (and its *Front-end consumers* table), `domain-map.md`.
   OpenAPI files are not exported yet (`architecture/contracts/README.md`); the endpoint list in
   `architecture/generated/<service>.md` is the reference, so re-run `scripts/extract_facts.py` and check it.

Rollout: backend that still serves the old form → web → backend clean-up.
