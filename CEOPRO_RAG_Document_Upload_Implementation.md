# Archived RAG upload implementation

This document described the previous FastAPI upload flow and mock mode. That contract is no longer active. RAG uploads are stored in CEOPRO, and query requests submit tenant documents through the stateless Gradio `rag_answer` API.

See [INTEGRATIONS.md](INTEGRATIONS.md#rag-and-document-extraction) for the current route, storage, and AI contract.
