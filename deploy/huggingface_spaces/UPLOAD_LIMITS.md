# Upload limits of the public CEOPRO-AI services

Applies to the two existing Spaces (URLs unchanged):

| Service | Endpoint | Limit |
|---|---|---|
| Extraction (`hhuuddaa/ceopro-ai-analytics`) | `extract_file` API and the web page's file picker | **500 MB** per file (`EXTRACTION_MAX_UPLOAD_MB`) |
| RAG (`hhuuddaa/ceopro-ai-models`) | `rag_answer` | **20 MB** per document (`RAG_MAX_DOC_MB`), 10 documents and **100 MB** per request (`RAG_MAX_REQUEST_MB`), at most **25,000 text passages** per request (`RAG_MAX_REQUEST_CHUNKS`, ≈ 20 MB of plain text) |

The defaults are in `ceopro-ai-analytics/feature_extraction.py` and
`ceopro-ai-models/feature_rag.py`. The environment variables exist only to
lower a limit on a Space without a code change. Before raising one, repeat the
measurements below.

## Deployment facts the limits are based on

- Both Spaces run Gradio 5.50.0 on `zero-a10g` hardware. The CEOPRO-AI code
  runs on the CPU in the main process, with a queue of 4 concurrent jobs per
  event (`default_concurrency_limit=4`).
- API callers send files base64-encoded inside the JSON body, so the body is
  about 4/3 of the file size. Bodies of 1, 30, 80, 200, 400 and 700 MB were
  accepted on the live request path (700 MB in 11.7 s). No proxy body limit
  was reached.
- Clients must allow long uploads. gradio_client's default httpx write
  timeout stops a ~500 MB upload on the client side, so use
  `Client(url, httpx_kwargs={"timeout": 900})` or the equivalent setting.

## Extraction: why 500 MB is safe

Each request processes at most the first 1,000 data rows, as before. The
service now reads files in a bounded way (`_read_bounded`), using the same
parsing as `file_dispatch.read_source_file()`'s CSV, XLSX and PDF adapters:

- **CSV:** reading stops after 1,001 rows.
- **XLSX:** openpyxl read-only streaming stops after 1,001 rows.
- **PDF:** pages are processed one at a time and closed. Reading stops once
  enough rows are found, and never goes past page 1,001.

The base64 payload is size-checked before anything is decoded. It is then
decoded in 4 MB steps to a temporary file, so there is no second in-memory
copy. Files uploaded through the web page are processed in place, and
Gradio's `max_file_size` rejects anything over 500 MB with HTTP 413.

An .xlsx/.xlsm is a zip archive, so a small upload can unpack to gigabytes.
Workbooks that unpack to more than 2,048 MB are rejected before parsing, as
are workbooks with more than 256 MB of shared strings. openpyxl holds the
shared strings in memory, and a full 1,048,576-row sheet of unique text
measured 163 MB.

On real files, the results are identical to the previous unbounded reader:
the guide's CSV template and the 51,947-row `Electronics_For_Test.xlsx` give
the same output apart from random staging IDs.

Measurements (local = same code and library versions, peak RSS includes the
test harness's own copy of the file):

| File | Local | Live Space |
|---|---|---|
| 499 MB CSV (near limit) | 5.4 s, 1.47 GB peak | 19.8 s, 1,000 rows, truncated |
| 501 MB CSV (over limit) | rejected | rejected in 15.6 s: "File is 501.2 MB; the maximum is 500 MB (524288000 bytes)." |
| 501 MB CSV via the web upload route | – | HTTP 413 "File size exceeded maximum allowed size of 524288000 bytes" |
| 499 MB CSV via the web upload route | – | 8.5 s |
| 490 MB scanned PDF (287 image pages) | 5.3 s, 1.44 GB peak | 22.2 s |
| 3,000-page text PDF (3.8 MB) | 132 s, 380 MB peak | 151.8 s (1,000 pages read) |
| 1,048,576-row XLSX, unique strings (62 MB, 475 MB unpacked) | 26.7 s, 797 MB peak | 31.6 s |
| 5 MB XLSX unpacking to 2,200 MB (zip bomb) | rejected in 0.0 s | rejected in 1.6 s |
| 4 concurrent requests: 2 × 499 MB CSV + 490 MB PDF + 62 MB XLSX | – | all completed in 34–54 s; Space stayed RUNNING |

Going above 500 MB was not chosen. The cost is no longer the parsing; it is
the upload itself, which needs ~667 MB of base64 in one JSON body plus the
decoded temporary file. With 4 concurrent jobs, that would grow past what
was verified on the live hardware, which has unspecified RAM.

## RAG: why 20 MB per document

RAG request time depends on how much text has to be embedded, not on the
file size. Every passage of 200 words, with a 40-word overlap, is embedded
on the CPU. Typical prose is about 6 bytes per word in English and about 10
bytes per word in Arabic, so a 20 MB plain-text document is up to ~22,000
passages. Measured live: 137 s end to end, about 160 passages/s including
extraction, retrieval, re-ranking and the Groq answer. A 20 MB PDF that is
mostly images has little text and finishes in seconds.

The per-request passage budget (25,000) lets one 20 MB plain-text document
through. It rejects a request that would take much longer, such as ten 20 MB
text files. The check runs before any embedding starts and the error message
says so.

Each document's text is extracted once with the pipeline's own
`data_access.fetch_document_text()`. That text is what the unmodified
`pipeline.ingest_pending_documents()` ingests. A document that cannot be
extracted is still marked `Failed`, exactly as before.

.docx and .xlsx files that unpack to more than 512 MB are rejected. Oversized
base64 is rejected from its length alone, before decoding.

| Request | Live Space |
|---|---|
| 21.1 MB .txt (over limit) | rejected in 1.6 s: "rag_over_21mb.txt: file is 21.1 MB; the maximum is 20 MB (20971520 bytes) per document." |
| 18.8 MB PDF (11 image pages with text) | answered correctly in 2.9 s |
| 19.8 MB plain-text document, 3.56 M words (~22,000 passages), one fact buried in it | answered correctly in 137.4 s ("Deliveries to Aqaba are dispatched every Tuesday and take four business days") |
| 4.6 MB .docx holding the same 19.8 MB of text | answered correctly in 138.6 s |
| 6 × 19 MB (114 MB) | rejected in 12.1 s: "The documents total more than 100 MB …" |
| 11 documents | rejected in 1.3 s: "At most 10 documents per request." |
| 0.9 MB .docx unpacking to 618 MB | rejected in 1.3 s: "unpacks to 618 MB; the maximum is 512 MB" |
| 19 MB of one-letter words (above the passage budget) | rejected in 1.9 s, before embedding: "The documents contain too much text for one request …" |

A larger per-document limit would only help image-heavy files. For
text-dense documents, request time grows with the text. 20 MB keeps one
request at about 2.5 minutes. With the queue's 4 concurrent jobs sharing
the CPU, that is roughly 10 minutes in the worst case. A limit two or three
times larger would push concurrent requests well past that, so 20 MB was
chosen.
