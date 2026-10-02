# MPI AI Integration

## Endpoint
`GET /mpi/summary` relative to `AI_SERVICE_URL`.

## Request
The backend sends `subject_type`, optional `subject_id`, and forwards Authorization.

## Response
The client accepts the existing discriminated contract:
- `OK`: MPI score plus sample-size, weighted sentiment, volume confidence, review count, recency/reliability weights, label counts, and evidence ID.
- `UNKNOWN`: evidence ID without an invented score.

All responses are validated with the existing Zod schemas before they leave the client boundary.

## Configuration
`AI_SERVICE_USE_MOCKS=true` enables the current mock MPI response.

## Failure handling
Timeouts, network failures, non-2xx responses, invalid JSON, and schema mismatches become `MpiClientError` and are handled by the existing controller/service flow.

## Boundary rule
The AI service computes MPI. CEOPRO continues to own authentication, tenant context, HTTP contracts, and any persistence/application policy around the result.
