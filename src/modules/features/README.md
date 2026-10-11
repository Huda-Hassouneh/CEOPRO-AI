# Features and entitlements

This module is CEOPRO's source of truth for the feature catalog, plan access, tenant usage, and several capacity checks. It answers two practical questions:

1. Is this feature included in the tenant's current subscription?
2. If the feature has a limit, how much has the tenant used or how much capacity remains?

The module does not implement every feature it gates. RAG, Data Connections, pricing, sentiment, forecasting, and other domains own their AI or business workflows and call the feature domain for entitlement and usage rules.

## Start with the scenario

### A tenant opens the usage page

The API finds the tenant's current access-granting subscription, ensures usage rows exist for metered plan features, and returns plan details plus an entitlement entry for each included feature. Boolean features have no numeric usage. Limited features report usage, remaining allowance, and whether the configured limit has been reached.

### A tenant uses a metered feature

The consuming domain checks the tenant's entitlement before doing work. For cumulative (`sum`) features, that domain records the consumed amount against the current billing period. A null plan limit means unlimited use. The feature domain provides the usage and capacity helpers; the business operation remains in the consuming domain.

Examples include RAG recording token usage after an AI response and Data Connections recording uploaded document size after valid extraction is staged. See the linked domain integration guides for the exact order of those operations.

### A tenant tries to add capacity

For capacity (`max`) features, current usage is read from the owning business data. The service compares existing usage plus the proposed addition with the plan limit. A null limit is unlimited. Capacity is not reset each billing period.

### A platform administrator changes a plan's features

Platform permissions protect feature and plan-feature management. The API validates the request, checks plan and feature relationships, and protects referenced or canonical records from unsafe removal. Tenant usage remains tenant-scoped.

## Feature model

| Model           | Meaning                                 | Usage behavior                                                                                     |
| --------------- | --------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `boolean`       | Access to a capability                  | No numeric meter; the catalog normalizes it to lifetime access semantics.                          |
| `limit` + `sum` | Consumable allowance                    | Usage is accumulated. Canonical metered features reset by billing period.                          |
| `limit` + `max` | Maximum concurrent or retained capacity | Usage is derived from current tenant data; the canonical capacity features use lifetime semantics. |

On a plan-feature link, `limit_value = null` means unlimited. A numeric limit is checked by the consuming operation. Boolean features cannot be assigned a numeric quota.

## Canonical feature catalog

The catalog in `types/feature.catalog.ts` defines these canonical codes. They represent subscription access and quotas; they do not by themselves prove that every associated product workflow is implemented in this module.

| Feature codes                                                                                                                                                                                                                    | Kind              | Aggregation / reset  |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------- | -------------------- |
| `dashboard_analytics`, `market_intelligence`, `market_perception`, `demand_prediction`, `inventory_intelligence`, `product_management`, `competitor_management`, `data_integration`, `business_recommendations`, `system_alerts` | Boolean access    | Lifetime             |
| `ai_pricing` (recommendations), `sentiment_analysis` (records), `rag_assistant` (tokens), `document_extraction` (KB), `report_generation` (reports), `marketing_image_generation` (images)                                       | Metered allowance | Sum / billing period |
| `tracked_competitors` (competitors), `tracked_products` (products), `connected_data_sources` (sources), `team_members` (members), `document_storage_mb` (MB)                                                                     | Capacity ceiling  | Max / lifetime       |

Legacy code aliases are `ai_queries` → `rag_assistant` and `pricing_intelligence` → `ai_pricing`. Use canonical codes for new plans and integrations.

## Capacity usage and source data

The `max` aggregation reads current counts from the system that owns the resource:

| Feature                  | Current usage comes from                                                          |
| ------------------------ | --------------------------------------------------------------------------------- |
| `tracked_competitors`    | Tenant competitor links where `is_tracked = true`                                 |
| `tracked_products`       | Tenant products that are not soft-deleted                                         |
| `connected_data_sources` | Tenant data sources where `is_active = true`                                      |
| `team_members`           | Tenant users that have not been removed                                           |
| `document_storage_mb`    | Sum of tenant RAG document metadata file sizes, divided by 1,048,576 bytes per MB |

If a `max` feature code has no resolver, the capacity service throws an error instead of inventing a usage value. The limits are enforced at the relevant resource-creation or upload call site; confirm each consumer checks before writing.

For `sum` features, `subscription_usage` is the persisted meter. The feature domain creates/ensures an allocation for the subscription and billing period. A consuming module increments it after its own success point. Boolean features and `max` features must not be incremented through the cumulative meter.

## API map

Paths below are relative to the application mount for this module. The module index mounts feature operations and management under `/features`, while plan-feature routes are mounted at the module root.

| Method and path                               | Purpose                                                                  | Access                                                                                                                  |
| --------------------------------------------- | ------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| `GET /features`                               | List the feature catalog                                                 | Authenticated platform user with `billing.read`                                                                         |
| `GET /features/:id`                           | Read one feature                                                         | Authenticated platform user with `billing.read`                                                                         |
| `POST /features`                              | Create a feature                                                         | Authenticated platform user with `billing.manage`                                                                       |
| `PATCH /features/:id`                         | Update a feature                                                         | Authenticated platform user with `billing.manage`                                                                       |
| `DELETE /features/:id`                        | Remove an unused custom feature                                          | Authenticated platform user with `billing.manage`; canonical or referenced features are protected                       |
| `GET /plans/:plan_id/features`                | List features and limits on a plan                                       | Authenticated platform user with `billing.read`                                                                         |
| `POST /plans/:plan_id/features`               | Link a feature to a plan                                                 | Authenticated platform user with `billing.manage`                                                                       |
| `PATCH /plans/:plan_id/features/:feature_id`  | Change a plan-feature limit                                              | Authenticated platform user with `billing.manage`                                                                       |
| `DELETE /plans/:plan_id/features/:feature_id` | Remove a plan-feature link                                               | Authenticated platform user with `billing.manage`; blocked when subscription or quote history references the plan       |
| `GET /subscriptions/current/usage`            | Return the tenant usage dashboard                                        | Authenticated tenant                                                                                                    |
| `POST /features/extraction/upload`            | Compatibility upload path; delegates to Data Connections upload handling | Authenticated tenant with `document_extraction` entitlement                                                             |
| `POST /features/extraction/process-pending`   | Legacy pending-processing path                                           | Authenticated tenant; returns HTTP 501 because the current extraction contract processes a submitted file synchronously |

The router validates request bodies and IDs before controllers run. The active route composition is in `index.ts` and `route/`. The parallel `routes/` directory and misspelled `features-managment` files are not imported by this module index; verify application wiring before changing or relying on those copies.

## Where to look

| Folder or file                 | Responsibility                                                                                           |
| ------------------------------ | -------------------------------------------------------------------------------------------------------- |
| `index.ts`                     | Composes the module's active routers                                                                     |
| `route/`                       | Active HTTP route and middleware composition                                                             |
| `controller/`                  | Request handling, access checks specific to plans, and response shaping                                  |
| `service/`                     | Feature semantics, plan links, usage-dashboard assembly, and capacity resolvers                          |
| `repo/`                        | Prisma queries and usage-meter persistence                                                               |
| `types/`                       | DTOs, validation schemas, and canonical feature definitions                                              |
| `client/features-ai.client.ts` | Standalone extraction client code; it is not imported by the active route/controller path in this folder |

## Related guides

- [RAG and extraction route ownership](RAG_AND_EXTRACTION_AI_INTEGRATION.md)
- [Data Connections README](../dataconnection/README.md)
- [Data Connections AI integration](../dataconnection/DATA_INGESTION_AI_INTEGRATION.md)
- [RAG AI integration](../rag/RAG_AI_INTEGRATION.md)
- [Repository AI integration contract](../../../INTEGRATIONS.md#ceopro-ai-service)

## End-to-end verification checklist

Use these blank checks during the real end-to-end run with the AI team. Record only results that have been observed and verified.

### Metrics and usage values

- [ ]
- [ ]
- [ ]
- [ ]
- [ ]

### Data this domain receives from or feeds to other systems

- [ ]
- [ ]
- [ ]
- [ ]
- [ ]
