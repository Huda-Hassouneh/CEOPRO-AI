# RAG module

Dedicated backend module for the tenant Knowledge Base / RAG experience.

Architecture:

`Route -> Controller -> Service -> Repo -> Prisma`

AI transport is isolated in:

`Service -> client/rag.client.ts -> CEOPRO AI API`

Public CEOPRO routes remain under `/features/rag/*`.

See `RAG_AI_INTEGRATION.md` for the AI connection contract and mock-mode switch.
