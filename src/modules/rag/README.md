# RAG module

Dedicated backend module for the tenant Knowledge Base / RAG experience.

Architecture:

`Route -> Controller -> Service -> Repo -> Prisma`

Uploads are stored in CEOPRO because the Gradio RAG API does not retain documents between requests. Query-time transport uses:

`Service -> client/rag.client.ts -> shared Gradio transport`

Public CEOPRO routes remain under `/features/rag/*`.

See `RAG_AI_INTEGRATION.md` for the active contract.
