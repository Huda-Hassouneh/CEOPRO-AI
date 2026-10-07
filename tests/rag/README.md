# RAG Document Upload Contract Tests

`rag-document-upload-contract.test.mjs` statically checks the backend contract for RAG document uploads.

It verifies:

- the RAG module is mounted under the existing `/features/rag` API prefix;
- POST document upload uses authentication, the `rag_assistant` entitlement, and multipart field `file`;
- the AI client calls `POST /rag/documents` and forwards `Authorization`;
- RAG AI mock mode defaults to true;
- only documented file extensions are accepted;
- the shared features router no longer owns duplicate RAG HTTP routes.

This is a source-contract test; it reads backend files and does not need the AI service to be online.
