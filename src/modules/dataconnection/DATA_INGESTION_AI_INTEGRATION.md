# Data Ingestion AI Integration

## Purpose
Defines the backend-to-AI contract used by the Data Connection domain for business-data extraction/processing.

## Configuration
`AI_SERVICE_URL` identifies the AI service. The current client also preserves its existing testing-mode mock branch.

## Upload
`client/ingestion.client.ts` sends multipart `POST /extraction/upload` with the sanitized original filename and forwards Authorization when provided.

The backend remains responsible for tenant context, entitlement checks, file limits, data-source/job persistence, and frontend-facing status. The AI service is responsible for extraction/mapping/promotion results and must return JSON.

## Pending processing
The client contains the existing `POST /extraction/process-pending?limit=...` contract. Triggering policy should be coordinated with the ingestion worker/scraping lifecycle; do not infer completion from the frontend.

## Security
Do not place credentials, passwords, tokens, API keys, or connection strings in `data_sources.metadata`. Secret ownership must use an appropriate secret/configuration mechanism outside this metadata contract.

## Failure handling
Timeout, invalid JSON, and non-success HTTP responses become the existing AI service error type so the controller can map them consistently.
