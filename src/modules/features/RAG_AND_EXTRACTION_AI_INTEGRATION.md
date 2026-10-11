# AI integration boundaries: features, RAG, and extraction

This guide explains how the Features and Entitlements module relates to AI-backed product flows. The key distinction is that this module owns subscription access and usage accounting; the RAG and Data Connections modules own their AI requests and business records.

## Quick ownership map

| Concern                                               | Owner                            | What the Features module does                                                                                                                                                  |
| ----------------------------------------------------- | -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Feature catalog and plan entitlements                 | `src/modules/features`           | Defines canonical codes, plan limits, access rules, and usage dashboard data                                                                                                   |
| RAG document upload and question answering            | `src/modules/rag`                | Provides the `rag_assistant` entitlement and token-usage meter; the RAG module owns document/query orchestration and its AI transport                                          |
| Business-file extraction and sales import             | `src/modules/dataconnection`     | Provides `document_extraction` and `document_storage_mb` entitlement/capacity checks; Data Connections owns template validation, extraction orchestration, staging, and import |
| Pricing, sentiment, forecasts, and other AI workflows | Their respective feature modules | Defines subscription access or quotas where configured; does not implement those workflows here                                                                                |

A catalog entry is an access or billing rule. It does not mean that the associated AI endpoint, calculation, persistence path, or downstream system is implemented in this folder.

## Scenario 1: Tenant asks a question about its knowledge base

1. The RAG API authenticates the user and tenant and checks the `rag_assistant` entitlement.
2. The RAG module selects the tenant's documents and submits the query through its AI integration. The existing integration notes identify the Gradio `rag_answer` API for this operation.
3. The RAG module validates and returns the answer.
4. Once the AI response provides actual token usage, the consuming domain records that amount against the tenant's `rag_assistant` sum allowance for the billing period.

The Features module does not send documents or questions to the AI service and does not calculate the answer. It provides the entitlement and stores the meter increment requested by the consuming code. For request/response and document-storage details, see [the RAG integration guide](../rag/RAG_AI_INTEGRATION.md).

## Scenario 2: Tenant uploads a business file for extraction

The compatibility endpoint `POST /features/extraction/upload` is mounted by the Features router. It requires authentication, tenant context, and the `document_extraction` entitlement, then delegates directly to `dataConnectionController.uploadFile`.

The Data Connections domain performs upload validation, template checks, AI extraction, response validation, persistence of source/job/staging records, and usage charging. Its current AI call is synchronous; downstream sales import is handled by its ingestion worker. Follow [the Data Connections AI integration guide](../dataconnection/DATA_INGESTION_AI_INTEGRATION.md) for the current template and extraction contract.

The `document_extraction` sum meter is measured in KB. The canonical catalog documents usage as `ceil(file_size_bytes / 1024)`. The separate `document_storage_mb` max entitlement reads stored document metadata and is measured from the tenant's accumulated file bytes in MiB. These two limits represent different resources.

## Scenario 3: A client requests pending extraction processing

The compatibility endpoint `POST /features/extraction/process-pending` remains mounted, validates its optional `limit` query, and checks `document_extraction` feature access. It then returns HTTP 501 with `NOT_IMPLEMENTED`: the current AI extraction contract processes each submitted file synchronously and does not provide pending batch processing through this endpoint.

## Usage and entitlement behavior

The tenant usage endpoint is `GET /subscriptions/current/usage`. Its response is assembled from the current access-granting subscription and its plan-feature links.

| Feature type       | Usage source                                                         | AI behavior                                                                                       |
| ------------------ | -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| Boolean            | Subscription-plan inclusion; no numeric meter                        | Enables or blocks access to the consuming workflow                                                |
| `limit` with `sum` | `subscription_usage` for the subscription and current billing period | The consumer increments usage by the amount actually consumed                                     |
| `limit` with `max` | Live tenant capacity from the owning tables                          | The consumer checks current usage plus the proposed addition before creating or storing more data |

An absent plan-feature link means the feature is not included. A null `limit_value` means unlimited use. Capacity features do not reset each billing period. The exact current-usage source for each canonical capacity feature is documented in [the module README](README.md#capacity-usage-and-source-data).

AI-facing feature codes in the canonical catalog include `rag_assistant`, `document_extraction`, `ai_pricing`, `sentiment_analysis`, `report_generation`, and `marketing_image_generation`. Other boolean codes gate product areas such as market intelligence, demand prediction, inventory intelligence, and business recommendations. The catalog does not show whether an AI team endpoint is live; check the owning module before relying on an integration.

## The standalone extraction client in this folder

`client/features-ai.client.ts` contains a standalone client, but the mounted extraction route does not call it. Within this folder, the live compatibility route delegates to the Data Connections controller, which owns the active shared AI transport. Treat the client below as unconnected legacy code unless application wiring is changed and verified.

If called directly, this client:

- Uses `AI_SERVICE_URL`, defaulting to `http://localhost:8000`.
- Sends a multipart request with field `file` to `POST extraction/upload`.
- Forwards an optional `Authorization` header and waits up to 60 seconds.
- Sanitizes the submitted filename and expects a JSON object response.
- Can return synthetic data when `AI_SERVICE_USE_MOCKS=true`.

The mock response is illustrative local data, not a valid proof of the live AI contract or a production extraction result. It contains fixed sample values and a generated-looking storage key; do not use those as authoritative CEOPRO job IDs, AI outputs, or persisted object locations. The active Data Connections path has its own validation and must be used for end-to-end verification.

## Security and responsibility boundaries

- Tenant identity comes from authenticated request context; consumers must not trust a tenant ID supplied only in an AI response.
- Feature limits and capacity are enforced by CEOPRO using subscription data and authoritative CEOPRO tables.
- AI output is not the source of CEOPRO identifiers, subscription usage records, or storage paths unless the owning module explicitly validates and persists such a value.
- Keep customer documents, contact details, prompts, and extracted values out of logs. Follow the owning integration's logging and retention rules.
- A successful entitlement check does not mean that an AI service is healthy or that its response is valid. Each consuming module must handle upstream failure and validate the returned contract.

## End-to-end verification checklist

Keep these entries empty until each item has been observed with the AI team and checked against CEOPRO's persisted data.

### Metrics and usage values

- [ ]
- [ ]
- [ ]
- [ ]
- [ ]

### Data exchanged with or delivered to other systems

- [ ]
- [ ]
- [ ]
- [ ]
- [ ]

## Related documentation

- [Features and Entitlements README](README.md)
- [Data Connections AI integration](../dataconnection/DATA_INGESTION_AI_INTEGRATION.md)
- [RAG AI integration](../rag/RAG_AI_INTEGRATION.md)
- [Repository AI integration contract](../../../INTEGRATIONS.md#ceopro-ai-service)
