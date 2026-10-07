# RAG and extraction route ownership

RAG routes belong to `src/modules/rag` and remain mounted at `/features/rag`. Uploads are stored in CEOPRO; queries submit tenant documents through the Gradio `rag_answer` API.

The compatibility extraction route `/features/extraction/upload` delegates to the Data Connection domain, which submits files to analytics `extract_file` and persists CEOPRO-owned ingestion records. `/features/extraction/process-pending` remains mounted and returns HTTP 501 because the current extraction contract is synchronous.

The user-facing route prefixes remain unchanged. See [`../../../INTEGRATIONS.md`](../../../INTEGRATIONS.md#ceopro-ai-service) for shared transport details.
