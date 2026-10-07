# RAG AI integration

The existing CEOPRO API remains under `/features/rag`:

- `POST /features/rag/documents` stores a tenant-owned source file in CEOPRO.
- `GET /features/rag/documents` and `GET /features/rag/chunks/:chunk_id` read local records.
- `POST /features/rag/query` loads up to ten tenant documents and calls the models Space `rag_answer` API.

The Gradio call uses positional input `[documents, question, top_k, history]`. Plain text and Markdown are sent as text; PDF, DOCX, and XLSX are Base64 encoded. Each upload is limited to 2 MB. Citation names are mapped back to local CEOPRO document and chunk IDs.

The RAG Space does not retain documents between calls, so CEOPRO stores the original bytes in `rag_documents_metadata.source_file_content`. Uploads do not make an upstream request.

See [`../../../INTEGRATIONS.md`](../../../INTEGRATIONS.md#rag-and-document-extraction) for shared transport configuration and the complete input contract.
