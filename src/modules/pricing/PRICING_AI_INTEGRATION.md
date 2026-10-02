# Pricing AI Integration

## Purpose
Defines how CEOPRO obtains an AI pricing recommendation while keeping evidence/input preparation server-authoritative.

## Endpoint
`POST /pricing/recommend` at `AI_SERVICE_URL`.

## Backend responsibilities
- Authenticate and resolve the tenant/product.
- Read authoritative pricing/competitor/business inputs from the repository.
- Build the request payload in the pricing service.
- Forward the authenticated request to the AI client.
- Validate the returned JSON contract before accepting it.
- Preserve `UNKNOWN` as a valid response state when the AI cannot produce a recommendation.

## AI responsibilities
Return a response matching the existing `AiPricingResponse` contract. Successful responses include action, current/suggested price, guardrail flags, matched competitor count, confidence score, and evidence/outcome identifiers. Unknown responses return the documented `UNKNOWN` shape.

## Configuration and failure handling
`AI_SERVICE_URL` selects the upstream; `AI_SERVICE_USE_MOCKS=true` enables the existing mock response. Timeouts, connection failures, non-2xx responses, malformed JSON, or schema mismatch remain external-service errors.

## Boundary rule
The AI service recommends; CEOPRO remains authoritative for tenant security, persisted evidence, pricing inputs, and any later business decision to apply a recommendation.
