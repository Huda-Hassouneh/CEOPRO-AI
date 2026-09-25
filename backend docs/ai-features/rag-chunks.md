# GET /features/rag/chunks/:chunk_id

Retrieves the exact source text content and associated file metadata for a specific document chunk. Used primarily by the frontend to display evidence and citation details when a user clicks a citation chip.

## Authentication & Authorization

| Requirement | Details |
|---|---|
| **Requires Auth** | Yes (`authenticateUser`, `requireTenant`) |
| **Requires Entitlement** | Yes (`rag_assistant` feature access required) |

## Path Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `chunk_id` | string (UUID) | Yes | The unique identifier of the vector chunk returned by the AI `/rag/query` endpoint. |

## Example Request

```http
GET /features/rag/chunks/c1f7a3b2-9d4e-48c5-a2b1-3e6f9a8d7c4b
Authorization: Bearer <access-token>
```

## Success Response

**200 OK**

```json
{
  "status": "success",
  "message": "Chunk fetched successfully",
  "data": {
    "chunk_id": "c1f7a3b2-9d4e-48c5-a2b1-3e6f9a8d7c4b",
    "text_content": "The expected Q3 marketing budget is strictly capped at $150,000...",
    "file_name": "2026_Q3_Marketing_Strategy.pdf"
  }
}
```

## Response Fields

| Field | Type | Description |
|---|---|---|
| `chunk_id` | string (UUID) | Unique identifier of the requested document chunk. |
| `text_content` | string | Exact source text contained in the document chunk. Used to display citation/evidence content in the frontend. |
| `file_name` | string | Name of the source file containing the chunk. |

## Error Responses

### 404 Not Found

Returned when:

- The specified `chunk_id` does not exist.
- The chunk exists but belongs to a different tenant.

### 403 Forbidden

Returned when the authenticated tenant does not have an active `rag_assistant` subscription entitlement.

## Notes

- The endpoint is intended primarily for frontend citation and evidence views.
- Access is tenant-scoped; a chunk belonging to another tenant must not be exposed.
- The `chunk_id` should normally come from a citation/vector chunk returned by the AI `/rag/query` endpoint.
