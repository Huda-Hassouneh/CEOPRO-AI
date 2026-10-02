# Data Connection Domain

## Purpose
Handles business-data file ingestion and persistent data-source management for a tenant.

## Structure
`index.ts -> route/ -> controller/ -> service/ -> repo/`, with `client/` for the external extraction service and `types/` for contracts/validation.

## Request flow
`HTTP -> dataconnection.route -> dataconnection.controller -> dataconnection.service -> repo/client`

## Important decisions
- Business-data ingestion stays separate from the Knowledge Base/RAG user experience even when both use extraction infrastructure.
- Uploads require tenant authentication and the `document_extraction` entitlement.
- Allowed upload formats and the 10 MB transport guard remain unchanged.
- Persistent source metadata must not contain secrets such as passwords, API keys, tokens, or connection strings.
- External AI/extraction HTTP details are isolated in `client/ingestion.client.ts`.
- Existing testing/mock behavior is preserved; this refactor does not alter when the client returns mocks.

## Primary data
`data_sources`, `ingestion_jobs`, `import_staging_rows`, and related ingestion tables through the repository.

## AI integration
See `DATA_INGESTION_AI_INTEGRATION.md`.
