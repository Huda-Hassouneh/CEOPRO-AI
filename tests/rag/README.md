# RAG Assistant tests

Read [RAG Assistant testing and diagnostics](RAG_ASSISTANT_TESTING.md) for the verified architecture, coverage matrix, known gaps, safe fixture requirements, commands, and report locations.

## Files

- `rag-document-upload-contract.test.mjs` — existing upload route, extension/size, Gradio adapter and route-mount source contracts.
- `rag-assistant-contract.test.mjs` — Feature 12 architecture, plans, meters, token/citation contracts, tenant predicates, retrieval window and failing regressions.
- `rag-assistant-client.test.ts` — deterministic tests of the real Node Gradio adapter using a controlled provider response.
- `fixtures/` — fictional business policies and a machine-readable answerable/abstention/security/11-document evaluation set.
- `../e2e/rag-assistant/` — shared-reporter Playwright diagnostics, plus independently gated live Gradio and AI-team FastAPI specs.

The Node Gradio contract is the active React web pathway. The AI Python indexed-RAG tests/spec are separate; passing them does not prove the hosted Gradio path. Live DB and provider tests require explicit safe local fixtures. Skipped scenarios are reported as BLOCKED.
