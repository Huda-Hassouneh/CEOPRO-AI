# AI and email integration tests

Use this folder when checking the service boundaries between the backend and its AI/email providers. The tests are deterministic and do not contact Hugging Face, Gmail, Resend, or a database.

## Run the suite

From the backend root:

```bash
npm run test:integration-services
```

Run a single test file with:

```bash
node --import tsx --test tests/integrations/ai/config.test.ts
```

## What each group checks

| Test location | Scenario | What it protects |
| --- | --- | --- |
| `../ai/gradio-client.test.ts` | A feature calls an AI Space | ZeroGPU token acquisition/caching/refresh, authenticated Gradio POST + SSE GET, timeout and upstream error handling |
| `ai/config.test.ts` | The app starts with AI settings | Space defaults and overrides, credentials, URL/HTTPS policy, timeout bounds, production mock restriction |
| `ai/feature-clients.test.ts` | A product feature calls Gradio | Positional argument order for extraction, MPI, forecast, pricing, sentiment, and RAG; representative response validation |
| `../auth/email-delivery.test.ts` | A signup message is prepared | MIME alternatives, escaped user content, and provider selection |
| `../auth/resend-email.test.ts` | Resend delivery is selected | API request shape and missing-key behavior, using a fake `fetch` |
| `email/gmail-smtp.test.ts` | Gmail SMTP sends or rejects a message | SMTP command sequence, MIME delivery, credentials sent as Base64 within the TLS protocol, and clean failure handling using a fake socket |
| `../rag/rag-document-upload-contract.test.mjs` | A RAG document is uploaded | Upload size contract matches the AI Space limit |

## When a test fails

1. Start with the failing test name and its file; each scenario is isolated.
2. If the shared Gradio protocol test fails, inspect `src/integrations/ai/config.ts`, `gradio.client.ts`, and `sse.ts`.
3. If a feature mapping fails, compare the feature client with the AI endpoint contract in `src/modules/<feature>/*AI*INTEGRATION.md` and the supplied Space API reference.
4. If delivery fails, inspect the email provider client and the provider-selection setting `EMAIL_DELIVERY_PROVIDER`.

These are mocked integration tests, not live-provider smoke tests. They intentionally avoid real credentials and billable or rate-limited service calls. Use an explicitly opt-in, separately configured smoke check if you later need to verify real provider credentials or deployment connectivity.
