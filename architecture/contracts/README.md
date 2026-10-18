# Contracts

Machine-readable contracts, preferably generated, never hand-edited:

- `openapi/<service>.json` — export from each service (`/v3/api-docs`, SpringDoc).
- `events/<EventName>.schema.json` — JSON Schema of each integration event payload.

Until CI generates them, export manually: run the service, then
`curl localhost:8048/v3/api-docs > openapi/stores-service.json`.
