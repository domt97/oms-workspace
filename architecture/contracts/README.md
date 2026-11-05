# Contracts

Machine-readable contracts, preferably generated, never hand-edited:

- `openapi/<service>.json` — export from each service (`/v3/api-docs`, SpringDoc). **Not exported yet**; until then the endpoint list in `architecture/generated/<service>.md` is the reference.
- `events/<MessageName>.schema.json` — JSON Schema of each integration message payload: events and commands between services (ADR 0006, e.g. `ReserveStock`). Envelope metadata such as the `correlationContext` header is not part of the payload (ADR 0004).

Until CI generates them, export manually: run the service, then
`curl localhost:8048/v3/api-docs > openapi/stores-service.json`.
