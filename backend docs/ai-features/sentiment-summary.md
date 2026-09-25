# AI Sentiment Summary

> **Latest codebase sync (2026-09-24):** Verified against `CEOPRO_Entitlements_CustomPlan_UX_Fixed.zip` with the later `CEOPRO_CustomPlan_Card_Alignment_Icons_Fix.zip` frontend overlay. Where older historical notes conflict with a “current behavior” section, the latest-codebase section is authoritative.

## 1. Endpoint Details

`GET /features/sentiment/summary`

**Runtime status:** Mounted by `modules/features/index.ts` under `/features`; authenticated tenant context is required.

## 2. Mental Model

Retrieves an aggregate sentiment view for a product, competitor, or business subject from the AI service.

## 3. Technical Decisions

The shared summary schema restricts subject type and UUID shape before the controller makes a provider GET. The response is curated to status, score, label counts, sample size, and evidence ID. This read route uses `requireFeatureAccess("sentiment_analysis")`, so an exhausted processing quota does not hide existing summaries.

## 4. Inputs

- Query: required `subject_type: PRODUCT | COMPETITOR | BUSINESS`; required `subject_id: string<uuid>`.
- Header: `Authorization: Bearer <JWT>` with tenant context.

## 5. Outputs

### Success

`200 OK`: `{ "success": true, "message": "Sentiment summary retrieved successfully", "data": { "status": "ok", "sentiment_score": 0.75, "label_counts": {}, "sample_size": 100, "evidence_id": "..." } }`.

### Errors

`400 INVALID_REQUEST` for missing subject fields; `502 EXTERNAL_SERVICE_ERROR` for provider failure; `500 INTERNAL_SERVER_ERROR` for unexpected errors.
