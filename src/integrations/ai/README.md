# AI Integration

This folder connects the CEO PRO backend to the AI team's Gradio services hosted on Hugging Face Spaces. It handles the connection and Gradio protocol; feature-specific services should still validate inputs and interpret each model's result.

## On this page

- [The request in one view](#the-request-in-one-view)
- [What each part does](#what-each-part-does)
- [Common request scenarios](#common-request-scenarios)
- [Configuration](#configuration)
- [Errors and where they come from](#errors-and-where-they-come-from)
- [Security responsibilities](#security-responsibilities)
- [Testing the integration](#testing-the-integration)
- [What the AI team must provide](#what-the-ai-team-must-provide)

## The request in one view

```text
CEO PRO feature/service
        │  service + endpoint name + ordered input data
        ▼
Gradio client
        │  gets a short-lived ZeroGPU token
        │  submits a job and receives an event ID
        │  reads the job's SSE result
        ▼
Hugging Face Space running the AI team's Gradio app
        │
        ▼
Raw result returned to the calling service
```

The client returns `unknown` because different AI endpoints can return different shapes. The feature-level service should check that shape before using it or returning it to the frontend.

## What each part does

| Part                 | Responsibility                                                                                                                                                                   |
| -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ai.types.ts`        | Defines the supported services (`models`, `analytics`), runtime configuration, client call contract, and integration error categories.                                           |
| `config.ts`          | Reads environment variables, selects the Space for a service, validates URLs and timeout settings, and rejects mock mode in production.                                          |
| Gradio client module | Gets and caches ZeroGPU tokens, submits Gradio jobs, retries once after a 401, and returns the result. It accepts injected fetch, time, and configuration functions for testing. |
| `sse.ts`             | Reads Gradio's Server-Sent Events (SSE) stream and extracts the result from its `complete` event.                                                                                |

### What one `call` does

1. Checks that `apiName` contains only allowed characters and is no longer than 100 characters.
2. Loads configuration for the requested service: `models` or `analytics`.
3. Gets a cached ZeroGPU token, or requests one from Hugging Face using the backend's Hugging Face access token.
4. Sends `POST /gradio_api/call/{apiName}` with `{ data }` and the `X-ZeroGPU-Token` header.
5. Validates the returned `event_id`.
6. Reads `GET /gradio_api/call/{apiName}/{event_id}` as an SSE stream.
7. Returns the only value in the `complete` event's JSON array.

The integration expects the completion payload to be an array containing exactly one result. Endpoint input order and the result's internal schema are defined by the AI team's endpoint contract, not by this generic client.

## Common request scenarios

### 1. A normal AI request succeeds

The calling feature chooses the correct service and endpoint, and passes the input values in the agreed order. The client submits the job, reads its SSE completion, and returns the result. The feature service then validates and maps that result for CEO PRO.

### 2. Several requests need a ZeroGPU token at once

Tokens are cached separately for `models` and `analytics`. If multiple requests for the same service need a token at the same time, they share the pending token request rather than requesting duplicate tokens. A cached token is refreshed before its expiry, using a default 90-second refresh margin.

### 3. Gradio responds with 401

The client clears that service's cached token, requests a fresh one, and retries the request once. If the retry still fails, the response is returned to the caller, which turns a non-success HTTP status into an `upstream_http` error.

### 4. The Space is slow or unreachable

Requests use a timeout. A timeout becomes a `timeout` error; connection failures become `network` errors. The SSE reader also cancels its stream when it times out or finishes.

### 5. The response does not match the Gradio contract

An invalid event ID, non-SSE result response, unreadable stream, invalid JSON, or completion payload with the wrong shape becomes a `malformed_response` error. A Gradio SSE `error` event becomes an `upstream_event` error.

## Configuration

| Environment variable       | Purpose                                                   | Default / rule                                             |
| -------------------------- | --------------------------------------------------------- | ---------------------------------------------------------- |
| `HUGGINGFACE_ACCESS_TOKEN` | Backend credential used to request ZeroGPU tokens.        | Required by `getGradioRuntimeConfig`. Keep it server-side. |
| `AI_MODELS_SPACE`          | Hugging Face Space ID for the `models` service.           | `hhuuddaa/ceopro-ai-models`                                |
| `AI_MODELS_SPACE_URL`      | Base URL for the `models` Space.                          | `https://hhuuddaa-ceopro-ai-models.hf.space`               |
| `AI_ANALYTICS_SPACE`       | Hugging Face Space ID for the `analytics` service.        | `hhuuddaa/ceopro-ai-analytics`                             |
| `AI_ANALYTICS_SPACE_URL`   | Base URL for the `analytics` Space.                       | `https://hhuuddaa-ceopro-ai-analytics.hf.space`            |
| `HUGGINGFACE_API_URL`      | Hugging Face API base URL used to request ZeroGPU tokens. | `https://huggingface.co`                                   |
| `AI_SERVICE_TIMEOUT_MS`    | Timeout in milliseconds for calls and result retrieval.   | `180000`; allowed range is 1000–600000.                    |
| `AI_SERVICE_USE_MOCKS`     | Enables mock mode where the application supports it.      | `true` is rejected when `NODE_ENV=production`.             |

Production Space URLs must use HTTPS. Space IDs and URLs can be overridden independently for each service.

## Errors and where they come from

| Kind                 | Meaning                                                                                                |
| -------------------- | ------------------------------------------------------------------------------------------------------ |
| `configuration`      | Missing or invalid environment configuration, invalid API name, or mock mode enabled in production.    |
| `timeout`            | A request or SSE result stream exceeded its timeout.                                                   |
| `network`            | Fetch failed before receiving an HTTP response.                                                        |
| `upstream_http`      | Hugging Face or Gradio returned a non-success HTTP response; its status is stored in `upstreamStatus`. |
| `malformed_response` | JSON, event ID, SSE content type, stream, or completion payload did not match expectations.            |
| `upstream_event`     | Gradio sent an SSE event indicating that the AI job failed.                                            |

These are integration errors, not user-facing messages. A route or feature service should log safe diagnostic details and map failures to the backend's normal API error contract. Avoid returning credentials, raw upstream response bodies, or internal URLs to users.

## Security responsibilities

- `HUGGINGFACE_ACCESS_TOKEN` is the backend's Hugging Face credential. Never send it to the browser or include it in API responses or logs.
- The short-lived ZeroGPU token is also an upstream credential. Keep its use inside the backend integration.
- Protect the CEO PRO route that calls this client with the app's authentication, tenant checks, and feature entitlement checks. A Hugging Face token is not a substitute for CEO PRO authorization.
- Apply suitable request limits and rate limits at the application boundary.
- Confirm Space visibility with the AI team. Public or protected Spaces can have publicly accessible running apps, so callers may be able to bypass CEO PRO route checks by calling a Space directly. Use an access arrangement that matches the product's requirements.
- Use a Hugging Face token with only the permissions needed for these Spaces, and rotate it if it is exposed.

## Testing the integration

`createGradioClient` accepts optional dependencies so tests can control external behavior:

- `fetchImpl` can return simulated Hugging Face and Gradio responses without making network calls.
- `getConfig` can provide test Space IDs, URLs, and timeouts.
- `now` can make token expiry and refresh behavior deterministic.
- `refreshSkewMs` can test when cached tokens should be refreshed.

Useful cases to cover include successful job submission and completion, concurrent token acquisition, token refresh after 401, HTTP errors, network failures, timeouts, invalid event IDs, malformed SSE/JSON, and Gradio error events. Keep tests independent of real Hugging Face credentials and production Spaces.

## What the AI team must provide

Before connecting a feature to a Space, confirm:

1. The Space ID and URL for the correct service (`models` or `analytics`).
2. The exact `apiName` for the endpoint.
3. The ordered input fields expected in `data` and their types.
4. The completion result schema, including how errors are represented.
5. Whether the endpoint requires ZeroGPU and what Hugging Face token permissions/access arrangement it needs.
6. Any expected processing time or file limits so the backend timeout and request validation can be set appropriately.

Do not guess endpoint names or input ordering. Treat the AI team's published Gradio API contract as the source of truth, and validate each endpoint's output in the feature-specific service before using it.
