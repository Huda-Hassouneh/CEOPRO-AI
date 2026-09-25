# GET /features/rag/documents

Retrieves a paginated list of all documents and files uploaded by the authenticated tenant for use within the RAG Knowledge Assistant.

## Authentication & Authorization

| Requirement | Details |
|---|---|
| **Requires Auth** | Yes (`authenticateUser`, `requireTenant`) |
| **Requires Entitlement** | Yes (`rag_assistant` feature access required) |

## Query Parameters

| Parameter | Type | Required | Description | Default |
|---|---|---|---|---:|
| `page` | integer | No | The page number for pagination. | `1` |
| `pageSize` | integer | No | The number of records per page. | `10` |

### Example Request

```http
GET /features/rag/documents?page=1&pageSize=10
Authorization: Bearer <access-token>
```

## Success Response

**200 OK**

```json
{
  "status": "success",
  "message": "Documents fetched successfully",
  "data": {
    "documents": [
      {
        "document_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
        "tenant_id": "tenant-uuid",
        "file_name": "2026_Q3_Marketing_Strategy.pdf",
        "storage_bucket_path": "raw-uploads/tenant-uuid/2026_Q3_Marketing_Strategy.pdf",
        "file_size_bytes": "4520192",
        "content_type": "application/pdf",
        "uploaded_by_user_id": "user-uuid",
        "uploaded_at": "2026-09-24T10:00:00.000Z"
      }
    ],
    "pagination": {
      "page": 1,
      "pageSize": 10,
      "total": 12,
      "totalPages": 2
    }
  }
}
```

## Response Fields

### Document Object

| Field | Type | Description |
|---|---|---|
| `document_id` | string (UUID) | Unique identifier of the document. |
| `tenant_id` | string (UUID) | Identifier of the tenant that owns the document. |
| `file_name` | string | Original name of the uploaded file. |
| `storage_bucket_path` | string | Storage path where the file is located. |
| `file_size_bytes` | string | File size in bytes. Returned as a string because PostgreSQL `BigInt` values are serialized as strings. |
| `content_type` | string | MIME type of the uploaded file. |
| `uploaded_by_user_id` | string (UUID) | Identifier of the user who uploaded the document. |
| `uploaded_at` | string (ISO 8601) | Timestamp indicating when the document was uploaded. |

### Pagination Object

| Field | Type | Description |
|---|---|---|
| `page` | integer | Current page number. |
| `pageSize` | integer | Number of records returned per page. |
| `total` | integer | Total number of documents available for the authenticated tenant. |
| `totalPages` | integer | Total number of available pages. |

## Notes

- Results are scoped to the **authenticated tenant**.
- Access requires authentication through `authenticateUser` and tenant resolution through `requireTenant`.
- The tenant must have access to the `rag_assistant` entitlement.
- `file_size_bytes` is intentionally returned as a string to prevent JSON serialization errors caused by PostgreSQL `BigInt` values.
