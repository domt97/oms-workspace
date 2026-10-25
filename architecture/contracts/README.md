# Contracts

Machine-readable contracts, preferably generated, never hand-edited:

- `openapi/<service>.json` — export from each service (`/v3/api-docs`, SpringDoc). **Not exported yet**; until then the endpoint list in `architecture/generated/<service>.md` is the reference.
- `events/<EventName>.schema.json` — JSON Schema of each integration event payload.

Until CI generates them, export manually: run the service, then
`curl localhost:8048/v3/api-docs > openapi/stores-service.json`.
