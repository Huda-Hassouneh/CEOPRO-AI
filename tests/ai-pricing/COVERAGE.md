# Feature 15 coverage matrix

Status is based on the source audit and commands actually executed for this package. `Contract` means a regression/source-contract test, not a runtime integration pass. Optional live/database rows stay `BLOCKED` until safe credentials and infrastructure are supplied.

| Area | Frontend | Node | PostgreSQL | AI | Current status |
|---|---|---|---|---|---|
| Standard plan exclusion | N/A | production catalog contract | N/A | N/A | PASS: 1 source contract |
| Custom-plan limits and subscription lifecycle | N/A | generic custom-plan limit persistence contract | No disposable billing fixture | N/A | PASS: generic persistence contract; runtime limits blocked |
| Entitlement enforcement / direct API | UI contract only | route regression test | No live tenant | Provider must not be called on denial | FAIL: route enforcement absent |
| Usage charging / billing period | N/A | service-order regression test | No safe tenant | Provider cost/charge semantics unresolved | FAIL: usage occurs after provider and missing allocation is ignored |
| Quota concurrency | N/A | atomic-reservation regression test | No safe concurrent fixture | No provider calls | FAIL: no reservation contract; runtime race test blocked |
| Refresh idempotency | button pending-state contract | idempotency regression test | no request-identity schema | provider work not deduplicated | FAIL: no request identity contract |
| Competitor selection | N/A | latest-eligible query regression | guarded Python fixture | deterministic source logic | FAIL: Node and Python do not collapse to latest observation; Python permits zero price |
| Currency / FX freshness | N/A | Node source regression | guarded Python fixture | deterministic Python FX function | FAIL: Node/Python freshness and positive-rate checks missing |
| Market average and decisions | display contract | market data passed through | Python helper/DB pipeline | deterministic thresholds | PASS: Python average, 5% boundaries, actions, UNKNOWN; DB blocked |
| Movement cap, cost floor, conflict | display contract | response schema | DB integration assertions | Python guardrails | PASS: current cap/floor behavior; floor exceeds cap in conflict and policy remains unresolved |
| Confidence | response rendering | schema bounds | N/A | heuristic cap test | PASS: bounded heuristic and response schema |
| Evidence provenance and persistence | local state only | Node evidence contract | Python DB verification | Python evidence IDs | FAIL: Node source IDs absent; Python source IDs present; DB persistence blocked |
| Catalog price safety | N/A | source regression | Python DB assertion | pipeline contract | PASS: source contract; DB assertion blocked |
| Tenant isolation / RLS | auth storage contract | authenticated tenant contract | restricted-role paired tenant suite | FastAPI context source contract | PASS: tenant context source checks; live RLS blocked |
| Gradio request/response | N/A | real client with controlled fixture | N/A | controlled response | PASS: client contract; live hosted call blocked |
| FastAPI pricing | N/A | separate route architecture check | dedicated HTTP harness absent | Python pipeline / guarded DB suite | PASS: architecture contract; HTTP integration blocked |
| English/Arabic UI | translated labels contract | N/A | N/A | N/A | PASS: locale key/source contract; authenticated browser check blocked |
| Full live E2E | opt-in browser | real Node API | verified QA DB | hosted Gradio | BLOCKED: approved tenant, DB, token, and hosted run not configured |
