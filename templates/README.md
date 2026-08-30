# CEOPRO Sales Transaction Import Template (v1)

`ceopro_sales_transaction_import_v1.csv` / `.xlsx` — the official, canonical
template for CSV/XLSX sales transaction uploads. Generated directly from
[`src/ai/extraction/template_contract.py`](../src/ai/extraction/template_contract.py)
(never hand-edit these files — run `python scripts/generate_import_templates.py`
after changing the contract) so the distributed template and the code that
validates against it can never silently drift apart.

## The guarantee

Upload a file using **exactly these column headers** (any order, extra
columns of your own are fine and preserved but ignored) and every value
that parses cleanly is guaranteed to make it through as clean, structured
data — nothing is silently dropped. If a specific cell still fails a
semantic check (e.g. a negative price), only that one field is set aside;
every other field in the row is still extracted. Any other format is
processed on a best-effort basis to extract the highest possible quality
of data, but the same nothing-silently-discarded guarantee on the raw
values still applies — every uploaded row's original values are always
preserved, in every case, regardless of format.

## Columns

| Column | Required | Type | Notes |
|---|---|---|---|
| `product_name` | Yes | Text | The product or line item name. |
| `quantity` | Yes | Whole number | Units sold. |
| `unit_price` | Yes | Number | Numeric only — **no currency symbol or code in this cell.** |
| `currency` | Yes | Text | 3-letter ISO code (`JOD`, `USD`, `SAR`, ...). |
| `transaction_date` | Yes | Date | `YYYY-MM-DD` preferred. |
| `discount_pct` | No | Number | Discount percentage, if any. |
| `invoice_id` | No | Text | Invoice number/reference. |
| `order_id` | No | Text | Order number/reference. |
| `email` | No | Text | Customer email, if collected. |
| `phone` | No | Text | Customer phone, if collected. |
| `competitor_name` | No | Text | A competitor mentioned in this record, if relevant. |
| `amount_raw` | No | Number | Total line amount, if independently available. |

`unit_price`/`amount_raw` are deliberately plain numbers with `currency`
broken into its own column, rather than a combined cell like `"24.50 JOD"`
— that combination has no reliable parser and would be an avoidable source
of failure in a template we control the shape of.

Each file includes one example data row — replace or delete it before
uploading your real data.

## PDF

There's no separate PDF template file here — a PDF is treated as
"standard" when it contains an actual table (not a scanned image) whose
header row uses these same column names; the same contract, the same
guarantee. See [`src/ai/extraction/adapters/pdf_adapter.py`](../src/ai/extraction/adapters/pdf_adapter.py).

## API / Database / POS / ERP integrations

These don't use a file template at all — pass an explicit field mapping
(`{your_field_name: canonical_field_name}`, using the canonical names in
the table above) to `ingestion_pipeline.process_records(..., trusted_field_mapping=...)`.
Since the caller already knows its own schema with certainty, this skips
header-matching entirely and gets the same guarantee as a fully compliant
file upload.
