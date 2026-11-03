# KEEL — Arabic AI Quality, RTL, RAG, Extraction and Marketing Audit

Audit date: 2026-11-03. Branch `claude/confident-bardeen-li9xpj`, base commit
`aaa725eb`. Everything below was **executed**; nothing is inferred from code
reading alone. Where a component could not be executed, it is marked
**BLOCKED** or **NOT TESTED** with the reason — no score is given for it.

Status legend: **PASS** (meets the stated threshold on the benchmark) ·
**PARTIAL** (works for some measured cases, fails others) · **FAIL** ·
**BLOCKED** (could not run here; reason given) · **NOT TESTED**.

## 0. Executive summary

| Capability | Before | After | Evidence |
|---|---|---|---|
| Arabic text from native PDFs (knowledge base + data import) | **FAIL** — CER 0.60–0.91, every Arabic word reversed, 126–732 presentation-form glyphs per file | **PASS** — CER 0.000–0.002 (browser-made), 0.017 (KEEL/ReportLab-made) | §3 |
| Arabic text from LibreOffice-made PDFs | FAIL (CER 0.79) | **PARTIAL** (CER 0.059 — remaining errors are LibreOffice's own broken glyph→Unicode map) | §3 |
| Scanned Arabic PDFs | **FAIL** — no text, document marked *Failed* | **PARTIAL** — prose CER 0.045; Arabic-Indic-digit invoice CER 0.52, numbers 12% | §3 |
| Two-column Arabic PDF reading order | FAIL (columns interleaved) | **PASS** (order 1.0, CER 0.000) | §3 |
| PDF tables with Arabic headers | FAIL (headers reversed glyphs, 0/3 rows) | **PASS** (logical headers, 3/3 rows) | §3 |
| Word tables | **FAIL** — tables silently dropped from the knowledge base | **PASS** | §3 |
| English text from browser-made PDFs | FAIL (all word spaces lost, WER 0.85) | **PASS** (CER 0.000) | §3 |
| Arabic keyword retrieval (MSA questions) | FAIL (hit@5 0.14) | **PASS** (hit@5 1.00, MRR 1.00, n=14) | §4 |
| Arabic RAG retrieval overall (41 answerable Qs, keyword tier) | FAIL (hit@5 0.07) | **PARTIAL** (hit@5 0.54, MRR 0.51) | §4 |
| Cross-language retrieval (EN↔AR) | FAIL | **BLOCKED** — needs the semantic embedding model; its weights could not be downloaded here | §4 |
| RAG answer generation / faithfulness / hallucination | — | **BLOCKED** — Groq rejects the configured key (HTTP 401); metering fails closed without a database | §4.5 |
| Arabic sales-report PDF export | **FAIL** — wrapped Arabic title printed in reverse line order; dates drawn `03-11-2026`; `<` in a name crashed the export | **PASS** | §5 |
| Frontend bidi isolation (assistant, products, import review) | PARTIAL | **PASS** for the audited surfaces (new tests) | §5 |
| Marketing copy generation (Arabic, Levantine, bilingual) | — | **BLOCKED** (same LLM blockers) — harness + human rubric ready | §6 |
| Marketing hashtags | FAIL (`#زيت زيتون` tags only `#زيت`) | **PASS** (normalised, tested) | §6 |
| AI image generation providers | — | **BLOCKED** — every hosted provider unreachable/credential-less in this sandbox | §7 |
| Arabic text inside images | not supported on AI images | **PASS** — new typography layer, OCR CER 0.014 mean | §7 |

**The single most severe finding:** before this change, every Arabic PDF a
customer uploaded to the Assistant or the Data Connections import was stored
as reversed presentation-form glyphs (`ﺔﻛﺮﺷ` instead of `شركة`). It looked
plausible in some viewers, but keyword search, citations, copy/paste and the
LLM context all received corrupted text, so Arabic PDF questions could not be
answered from the document. This is fixed at the extraction layer, without
reversing any strings by hand: KEEL now inverts the Unicode Bidi Algorithm and
**verifies** each line by re-running the forward algorithm.

## 1. AI model and provider inventory

Measured = from this audit's executed benchmark. Cost = what KEEL's own code
and docs state; no prices were invented.

| Model / engine (exact) | Provider | KEEL purpose | Arabic (measured) | English (measured) | Accuracy | Latency | Reliability | Cost | Limitations | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| `openai/gpt-oss-20b` (`GROQ_MODEL`) | Groq (hosted) | Assistant answers, marketing copy, marketing factual review | not measurable | not measurable | — | — | 5/5 benchmark calls refused: `BudgetError ACCOUNTING_UNAVAILABLE` (no DB); direct API call: HTTP 401 *Invalid API Key* | Free tier / quota-limited; needs approved cost schedule (docs/INTEGRATIONS.md) | reasoning model: hidden reasoning shares `max_tokens` (llm_client.py) | **BLOCKED** |
| Local llama-server (docs: Qwen2.5-3B-Instruct Q5_K_M) | self-hosted | optional chat backend | — | — | — | docs: ~6 tok/s CPU | — | free (own hardware) | not running here | **NOT TESTED** |
| HF Inference router (`HUGGINGFACE_LLM_MODEL`) | Hugging Face | optional chat backend | — | — | — | — | token rejected: *User Access Token "ceopro-deploy" is expired* | quota-limited | — | **BLOCKED** |
| `PAID_LLM_*` slot | any OpenAI-compatible | optional | — | — | — | — | not configured | paid | requires approval | **NOT TESTED** |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (torch or ONNX `model_quint8_avx2`) | local weights from HF | RAG semantic retrieval, admission filter | — | — | — | — | download HTTP 401 (expired injected token) → KEEL fell back to keyword search as designed | free | 256-token window (`RAG_EMBEDDING_MAX_SEQ_LENGTH`) | **BLOCKED** |
| `sentence-transformers/static-similarity-mrl-multilingual-v1@384` | local weights from HF | low-memory semantic backend | — | — | — | — | same download failure | free | — | **BLOCKED** |
| `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` | local weights from HF | RAG re-ranking | — | — | — | — | same download failure | free | ~1.8 GB RSS with torch embedder (pipeline.py) | **BLOCKED** |
| BM25Plus (`rank-bm25`) + KEEL tokenizer | local | keyword retrieval (always on; sole tier when the model is unavailable) | MSA hit@5 0.14 → **1.00**; Levantine 0.14 → 0.57 | EN→AR 0.00 (lexical cannot cross languages) | see §4 | 1.6 ms/query (7 chunks) | 43/43 queries ran | free | no synonyms/dialect/cross-language | **PARTIAL** |
| pdfplumber 0.11 / pdfminer + **new** `extraction/pdf_text.py` | local | PDF text for knowledge base and data import | CER 0.85 → **0.002** (Chromium) | CER 0.22 → **0.000** | §3 | 0.07–0.68 s/file | 14/14 files processed | free | LibreOffice ToUnicode defects remain | **PASS** (digital) |
| Tesseract 5.3.4, `ara+eng` (Ubuntu tessdata), **new** fallback | local binary | scanned PDF pages | prose CER 0.045; Indic-digit invoice CER 0.52 | — | numbers 0.75 / 0.12 | 1.4–3.3 s/doc | 2/2 scans produced text (was 0/2) | free | stock model reads Arabic-Indic digits poorly; tables weak | **PARTIAL** |
| python-docx 1.x | local | Word ingestion | CER 0.00 (tables now included) | — | table rows 1.0 | 0.13–0.38 s | 3/3 | free | headers/footers/text boxes not read | **PASS** |
| openpyxl 3.1 | local | Excel ingestion | CER 0.065 (number formatting `9.0` vs `9.00`), numbers 1.0 | — | — | 0.04 s | 1/1 | free | data import reads the active sheet only | **PASS** |
| `cardiffnlp/twitter-xlm-roberta-base-sentiment` | local weights from HF | review sentiment | — | — | — | — | weights not downloadable | free | — | **BLOCKED** |
| `demand_forecast_xgboost` (XGBoost) + baselines | local | demand prediction | language-independent | — | not re-measured in this audit | — | its existing unit tests pass in the full suite | free | — | **NOT TESTED** (out of language scope) |
| `competitor-classification-v1`, `star-rating-v1` | local rules | competitor scope, rating sentiment | not measured | — | — | — | — | free | — | **NOT TESTED** |
| `gemini-2.5-flash` / `meta-llama/llama-4-scout-17b-16e-instruct` (vision) | Google / Groq | menu pictures (market discovery) | — | — | — | — | no credentials | quota-limited | — | **NOT TESTED** |
| Image: `@cf/black-forest-labs/flux-1-schnell`, `black-forest-labs/FLUX.1-schnell` (HF), `FLUX.1-schnell-Free` (Together), `gemini-2.5-flash-image`, Pollinations `flux`, AI Horde, local server | hosted / self-hosted | marketing images | — | — | — | — | aihorde.net, router.huggingface.co, image.pollinations.ai unreachable from this sandbox (egress policy); no other keys | free tiers (per module docs) | none can spell Arabic reliably (see §7) | **BLOCKED** |
| Designed poster (Pillow + arabic-reshaper + python-bidi) | local | image fallback | Arabic headline shaped correctly (visual check) | — | — | <1 s | always available | free | not AI-generated (labelled) | **PASS** |
| **New** typography layer (`marketing/typography.py`, Pillow + libraqm/HarfBuzz) | local | Arabic/English text over AI images | OCR CER 0.000–0.065 per element | OCR CER 0.000 | mean 0.014 | <0.5 s | 10/10 renders | free | needs an Arabic font (bundled DejaVu works) | **PASS** |
| rembg `u2netp` | local, opt-in | background removal | — | — | — | — | not installed by default | free | ~520 MB peak RSS (module docs) | **NOT TESTED** |
| Video generation | — | — | — | — | — | — | not implemented by design (video_generation.py) | — | — | **NOT TESTED** |

## 2. Benchmark design (reproducible)

Code: `backend/scripts/arabic_benchmark/`.

- `ground_truth.py` — synthetic company “شركة الندى للتجارة (Al-Nada Trading
  Demo)”. **No customer data.** 7 source documents (Arabic policy with
  diacritics/URL/e-mail/dates/SKU, Arabic contract with a price table and
  IBAN, Arabic price list workbook with Arabic-Indic digits as text, 3-page
  mixed Arabic/English quarterly report, two-column Arabic newsletter, English
  handbook, Arabic-Indic invoice with fields and a table), the RAG question
  set, marketing prompts and RTL strings. All text is stored in Unicode
  logical order.
- `build_corpus.py` — produces 14 files the way they reach KEEL in practice:
  headless **Chromium** “Save as PDF” (Skia/HarfBuzz), **LibreOffice**
  (docx→pdf), **ReportLab + arabic-reshaper + python-bidi** (KEEL's own export
  technique), **simulated scans** (200 dpi, ±0.8° rotation, blur, noise,
  image-only PDF), **python-docx** with RTL paragraphs/tables, **openpyxl**.
- `metrics.py` — CER/WER (Levenshtein; whitespace-only normalisation, so
  presentation forms, reversed letters and lost diacritics *count as errors*),
  missing/duplicated/reversed-word rates, Arabic-letter recall, presentation
  form count, diacritic recall, numeric accuracy (Arabic-Indic digits
  normalised, exact-token match), paragraph reading-order accuracy, table-row
  accuracy (all cells of a row on one line), field accuracy (value on its
  label's line), P@K/R@K/hit@K/MRR/nDCG@K.
- `run_benchmark.py` — runs KEEL's **real** code paths: knowledge-base
  ingestion `rag/data_access.fetch_document_text()` (via an in-memory MinIO
  stand-in), Data Connections import `extraction/file_dispatch.read_source_file()`,
  the RAG retrieval stack (`chunk_text` → `BM25Index` → FAISS/RRF/re-ranker
  when available → the advisor's own `_chunk_filter`), the sales PDF export
  (rendered, OCR'd and read back), and the typography layer (OCR'd).
- `marketing_eval.py` — marketing generation through the real
  `content_generator`, automated checks and a human rubric (requires `--llm`).

Commands (from `backend/`, Python 3.12 venv with `src/ai/requirements.txt`,
plus `tesseract-ocr tesseract-ocr-ara` and LibreOffice/Chromium for the corpus):

```bash
python -m scripts.arabic_benchmark.run_benchmark --json arabic-benchmark.json
```

```bash
python -m scripts.arabic_benchmark.marketing_eval --llm --out marketing-eval
```

```bash
python -m pytest -q src/ai/tests/test_arabic_text_quality.py
```

```bash
cd ../frontend && node --test tests/rtlBidi.test.mjs
```

“Before” = the same runner against the unmodified tracked code (the changed
modules stashed); “after” = this branch.

## 3. Arabic document extraction

### 3.1 Knowledge-base path (`fetch_document_text`, what the Assistant indexes)

| File | Producer | Lang | CER before → after | WER before → after | Missing words | Arabic letters kept | Presentation-form chars | Numbers | Reading order | Table rows | Fields |
|---|---|---|---|---|---|---|---|---|---|---|---|
| policy_ar.chromium.pdf | Chromium | ar | 0.8485 → **0.0018** | 1.1714 → 0.0057 | 0.93 → 0.006 | 0.26 → 1.00 | 555 → 0 | 0.75 → 1.00 | 0.0 → 1.0 | – | – |
| policy_ar.libreoffice.pdf | LibreOffice | ar | 0.7856 → **0.0593** | 1.0857 → 0.2629 | 0.90 → 0.20 | 1.00 → 1.00 | 0 → 0 | 0.81 → 1.00 | 0.0 → 1.0 | – | – |
| policy_ar.reportlab.pdf | ReportLab (KEEL style) | ar | 0.8549 → **0.0173** | 0.9829 → 0.0914 | 0.92 → 0.09 | 0.00 → 1.00 | 732 → 0 | 0.88 → 1.00 | 0.0 → 1.0 | – | – |
| policy_ar.scanned.pdf | scan | ar | 1.0000 → **0.0447** | 1.00 → 0.13 | 1.00 → 0.13 | 0.00 → 0.97 | 0 → 0 | 0.00 → 0.75 | 0.0 → 1.0 | – | – |
| policy_ar.docx | Word | ar | 0.0000 → 0.0000 | 0 → 0 | 0 → 0 | 1.00 | 0 | 1.00 | 1.0 | – | – |
| contract_ar.docx | Word + table | ar | 0.2974 → **0.0000** | 0.32 → 0 | 0.32 → 0 | 0.74 → 1.00 | 0 | 0.50 → 1.00 | 1.0 | 0.00 → **1.00** | – |
| contract_ar.pdf | Chromium + table | ar | 0.8480 → **0.0000** | 1.13 → 0 | 0.86 → 0 | 0.25 → 1.00 | 289 → 0 | 0.70 → 1.00 | 0.0 → 1.0 | 0.00 → **1.00** | – |
| price_list_ar.xlsx | Excel | ar | 0.0651 → 0.0651 | 0.07 → 0.07 | 0.05 | 0.94 | 0 | 1.00 | 0.9 | 0.83 | – |
| mixed_report_q1.pdf | Chromium, 3 pages | mixed | 0.6046 → **0.0000** | 0.95 → 0 | 0.90 → 0 | 0.23 → 1.00 | 196 → 0 | 0.60 → 1.00 | 0.0 → 1.0 | – | – |
| mixed_report_q1.docx | Word | mixed | 0.0000 → 0.0000 | 0 → 0 | 0 | 1.00 | 0 | 1.00 | 1.0 | – | – |
| newsletter_2col_ar.pdf | Chromium, 2 columns | ar | 0.9097 → **0.0000** | 1.13 → 0 | 0.87 → 0 | 0.21 → 1.00 | 245 → 0 | 1.00 | 0.0 → **1.0** | – | – |
| handbook_en.pdf | Chromium | en | 0.2155 → **0.0000** | 0.85 → 0 | 0.84 → 0 | – | 0 | 0.88 → 1.00 | 0.0 → 1.0 | – | – |
| invoice_ar_indic.pdf | Chromium, Arabic-Indic digits | ar | 0.7980 → **0.0000** | 1.00 → 0 | 0.71 → 0 | 0.24 → 1.00 | 126 → 0 | 0.82 → 1.00 | 0.0 → 1.0 | 0.00 → **1.00** | 0.00 → **1.00** |
| invoice_ar_indic.scanned.pdf | scan, Arabic-Indic digits | ar | 1.0000 → 0.5185 | 1.00 → 0.76 | 1.00 → 0.61 | 0.00 → 0.73 | 0 | 0.00 → **0.12** | 0.0 → 0.0 | 0.00 → 0.00 | 0.00 → 0.17 |

Processing success (non-empty text): 12/14 → **14/14**. Extraction time after
the fix: 0.04–0.68 s per digital file, 1.4–3.3 s per scanned document (OCR).
Sample size: 14 files, 7 documents, ~3,900 reference characters.

**Corruption vs. display.** The “before” Arabic output was genuinely corrupted
*underlying text*, not a viewer artefact: code points were presentation forms
(U+FE70–FEFF) in reversed order (e.g. `ةرﺎﺠﺘﻠﻟ ىﺪﻨﻟا ﺔﻛﺮﺷ` for
`شركة الندى للتجارة`), lam-alef ligatures split (`لالخ` for `خلال`), and
shadda/tanween detached onto spaces. A correct string would have contained
only U+0600–U+06FF letters in logical order; the metrics compare code points,
not rendering. After the fix, the Arabic-letter recall is 1.0 and no
presentation-form code point remains in any digital file.

Residual errors after the fix (all inspected by diff):

- Chromium: one shadda+fatha glyph (in `إِنَّ`) is written by Chromium with **no
  Unicode mapping** (`\x00`); the mark is unrecoverable from the PDF.
- ReportLab/KEEL-style PDFs: `arabic-reshaper` deletes harakat at creation
  (CER 0.017 is exactly the missing diacritics); letters and order are exact.
- LibreOffice: its ToUnicode map assigns `مّ` to every use of a medial-mim glyph
  first seen with a shadda, `<`/`Z` to some tanween/damma glyphs. These are
  producer defects in the PDF; KEEL now reads the order correctly (reading
  order 1.0, numbers 1.0) but cannot recover the wrong mappings.
- Scanned Arabic-Indic invoice: tesseract's stock `ara` model misreads
  Arabic-Indic digits (٢٠٢٦ → `1١77`) and drops ruled table rows; ruling-line
  removal (added) improved CER 0.60 → 0.44 in a controlled test but numbers
  stay unusable. **FAIL for scanned Arabic-Indic invoices** — see §11.

### 3.2 Data Connections import path (`read_source_file`)

| File | CER before → after | Numbers | Table rows | Headers before → after |
|---|---|---|---|---|
| contract_ar.pdf | 0.86 → 0.70* | 0.6 → 0.6* | 0.00 → **1.00** | `ﺞﺘﻨﻤﻟا ﺰﻣر`… → `رمز المنتج`, `اسم المنتج`, `سعر الوحدة (دينار)`, `الحد الأدنى للطلب` |
| invoice_ar_indic.pdf | 0.82 → 0.56* | 0.65 → 0.65* | 0.00 → **1.00** | `ﻒﻨﺼﻟا`… → `الصنف`, `الكمية`, `سعر الوحدة`, `المجموع` |
| policy_ar.chromium.pdf | 0.85 → 0.011 | 0.75 → 1.00 | – | page text |
| mixed_report_q1.pdf | 0.60 → 0.013 | 0.60 → 1.00 | – | page text |
| newsletter_2col_ar.pdf | 0.93 → 0.023 | 1.00 | – | page text |
| handbook_en.pdf | 0.24 → 0.022 | 0.88 → 1.00 | – | page text |
| policy_ar.scanned.pdf | 0.99 → 0.054 | 0.00 → 0.75 | – | page text (OCR) |
| price_list_ar.xlsx | 0.27 → 0.27* | 1.00 | 0.67* | unchanged (already logical) |

\* By design the import adapter returns only a PDF's table rows when it has a
table (documented scope boundary in `pdf_adapter.py`), and only the active
worksheet of a workbook; text outside the table/second sheet is therefore not
in the import output. Before the fix, the Arabic header names could never
match KEEL's template synonyms, so an Arabic PDF price list could not be mapped.

## 4. Arabic RAG retrieval

### 4.1 Setup

Knowledge base: 7 files (`RAG_CORPUS`); a scanned variant replaces the policy
and invoice by their scans. 43 questions: 14 MSA, 7 Jordanian/Levantine,
8 English-about-Arabic, 6 Arabic-about-English, 2 mixed AR/EN, 2 synonym
paraphrases, 1 with diacritics, 1 with keyboard spelling variants
(`اوقات خدمه`), 2 unanswerable. A retrieved chunk is **relevant** only when the
gold passage's evidence span (e.g. `2.50 دينار`, `OL-1000`, `21 days`) is
literally findable in it after search normalisation — i.e. the answer is
readable from that chunk. *Retrieval* = ranked output of BM25/RRF; *admitted*
= after the advisor's relevance filter, i.e. what reaches the LLM.

Semantic embeddings and the re-ranker were **unavailable** (weights not
downloadable), so these numbers are KEEL's **keyword tier** — exactly what
production runs whenever the model is unavailable. The documents are short,
so with the default 200-word window each is one chunk (document-level
retrieval); a 40-word passage run is included as a sensitivity check.

### 4.2 Results (41 answerable questions)

| Run | Stage | MRR | P@1 | P@5 | R@5 | hit@1 | hit@5 | nDCG@5 |
|---|---|---|---|---|---|---|---|---|
| native corpus | retrieval | 0.104 → **0.611** | 0.098 → 0.537 | 0.024 → 0.156 | 0.122 → 0.687 | 0.098 → 0.537 | 0.122 → **0.707** | 0.108 → 0.620 |
| native corpus | admitted | 0.073 → **0.512** | 0.073 → 0.488 | 0.015 → 0.107 | 0.073 → 0.520 | 0.073 → 0.488 | 0.073 → **0.537** | 0.073 → 0.506 |
| scanned variant | admitted | 0.073 → 0.390 | 0.073 → 0.366 | 0.015 → 0.083 | 0.073 → 0.398 | 0.073 → 0.366 | 0.073 → 0.415 | 0.073 → 0.384 |
| 40-word passages | admitted | 0.073 → 0.451 | 0.073 → 0.415 | 0.015 → 0.137 | 0.061 → 0.463 | 0.073 → 0.415 | 0.073 → 0.488 | 0.064 → 0.446 |

By question type (native corpus, admitted):

| Type | n | hit@1 before → after | hit@5 before → after | MRR before → after |
|---|---|---|---|---|
| MSA | 14 | 0.14 → **1.00** | 0.14 → **1.00** | 0.14 → **1.00** |
| Diacritics in question | 1 | 0 → 1 | 0 → 1 | 0 → 1 |
| Spelling variants | 1 | 0 → 1 | 0 → 1 | 0 → 1 |
| Jordanian/Levantine | 7 | 0.14 → 0.29 | 0.14 → 0.57 | 0.14 → 0.43 |
| Arabic about English docs | 6 | 0 → 0.33 | 0 → 0.33 | 0 → 0.33 |
| English about Arabic docs | 8 | 0 → 0 | 0 → 0 | 0 → 0 |
| Mixed AR/EN | 2 | 0 → 0 | 0 → 0 | 0 → 0 |
| Synonym paraphrase | 2 | 0 → 0 | 0 → 0 | 0 → 0 |

Unanswerable questions: 2/2 (before) and 1/2 (after) had no admitted
evidence; after the fix the “remote-work policy” question admits the returns
*policy* document (it shares `سياسة` + `الشركة`), so declining relies on the
LLM's grounding prompt — not verifiable here (§4.5). Mean query time 1.6 ms.

### 4.3 What changed and why

1. **Extraction** (§3) — the largest effect: retrieval cannot find what was
   stored reversed.
2. **`bm25_index.tokenize` now folds for search** (`core/arabic_text.py`):
   diacritics/tatweel removed (Python's `\w` does not match combining marks,
   so `إِنَّ` used to split into `إ`, `ن`), أ/إ/آ/ٱ→ا, ى→ي, ة→ه, Arabic-Indic
   digits → 0-9, presentation forms → letters. Stored text is unchanged.
3. **Advisor relevance filter** matches words with attached proclitics
   (`بقسيمة` ~ `قسيمة`): admitted hit@5 0.512 → 0.537.

### 4.4 Remaining retrieval failures (measured)

All 8 English-about-Arabic, both mixed and both synonym questions still fail,
plus 3/7 Levantine and 4/6 Arabic-about-English: these need **meaning**, not
shared words (`refund` ↔ `يُعاد المبلغ`, `خربان` ↔ `تالف`). KEEL's design
answers them with the multilingual embedding model + re-ranker, which this
sandbox could not download. They must be re-measured with
`run_benchmark.py` on a host where `RAG_EMBEDDING_BACKEND` is available
(§12, action 1). A hand-written synonym list tuned on these 43 questions was
deliberately **not** added: it would overfit the benchmark.

### 4.5 Answer correctness, faithfulness, citations — BLOCKED

`run_benchmark.py --llm` generates answers through `llm_client` and checks the
gold facts are stated; `marketing_eval.py` uses the same provider. Neither
could run: (a) credit metering requires the database and **fails closed**
(`BudgetError ACCOUNTING_UNAVAILABLE`), which is correct behaviour; (b) a
direct request with the configured Groq key returned **HTTP 401 Invalid API
Key**. No answer-quality, hallucination-rate or citation-correctness number is
claimed. Citation *page numbers* depend on the form-feed page breaks, which
the new extractor preserves (`chunk_pages`), and OCR'd pages keep their place.

## 5. RTL and Unicode across the product

| Hop | Test | Result |
|---|---|---|
| JSON (API), UTF-8 bytes (DB), CSV export | 7 mixed RTL/LTR strings (codes, URLs, dates, Arabic-Indic digits, diacritics, Arabic punctuation) round-tripped by code point | **PASS** 7/7 (before and after) |
| Knowledge-base chunks/citations | logical order now stored (§3) | **PASS** after fix |
| Sales report PDF (Arabic) | rendered → OCR'd + read back in logical order | before **FAIL**: wrapped title printed with its *second* half first; generation date drawn `03-11-2026`; a `<` in a company/product name crashed `render_pdf`. After **PASS**: title order, date `2026-11-03 19:15 UTC`, `INV-2026-0042`, mirrored brackets `(حسب الإيرادات)` correct |
| Frontend: assistant full answers | SSR test | before: only the summary had `dir="auto"`; an English paragraph in the Arabic UI was laid out RTL (punctuation on the wrong side). After: every paragraph, heading, list item and table cell takes its own direction |
| Frontend: product names / import review | SSR test | product names and imported rows now isolated with `<bdi>` (ProductsListPage, QuickSaleModal, StructuredImportReview) |
| Frontend sources and Arabic locales | static test | no presentation forms, no LRO/RLO overrides, Arabic translations in logical order (no word starting with ة/ى) — **PASS** |
| Locale direction | `getLocaleDirection` | `ar` → `rtl`, `en` → `ltr` — **PASS** |
| Marketing images | typography layer | §7 — **PASS** |
| Notifications / e-mail templates, Word exports | — | **NOT TESTED** (no Arabic e-mail rendering harness; KEEL has no Word export) |

Why dates looked reversed: per the Unicode Bidi Algorithm, Western digits
after Arabic letters become Arabic numbers (rule W2) and `-` does not join
them, so `2026-11-03` is *correctly* displayed `03-11-2026` unless isolated.
The fix embeds such tokens left-to-right before reordering; nothing is
reversed by hand. `INV-2026-0042` is left alone (it is already one LTR run).

## 6. Arabic marketing

**Generation quality: BLOCKED** (same LLM blockers as §4.5). The evaluation
harness is ready: `scripts/arabic_benchmark/marketing_eval.py --llm` runs 5
prompts (Arabic storytelling, **Jordanian dialect** TikTok, formal Facebook,
Ramadan Instagram + Google Ads, English/bilingual) through the real generator
and factual review, then applies automated checks — Arabic-script share ≥ 0.8
for Arabic outputs, valid single-token hashtags, Google Ads ≤30/≤90 chars,
**any number/price/percentage not present in the product facts**, origin/
certification/health/discount wording, presentation forms/overrides — and
writes `rubric.csv` for **two human reviewers** (grammar, spelling, fluency,
dialect, cultural fit, persuasiveness, relevance, brand voice, hashtags,
platform format; 1–5 definitions in the script). An LLM scoring its own copy
is not used as an accuracy measure.

Measured / verified without an LLM:

| Item | Finding | Status |
|---|---|---|
| Platforms supported | Instagram, Facebook, TikTok, Google Ads only (`content_generator.PLATFORMS`) | LinkedIn posts, TikTok scripts, SEO titles/descriptions, long/short product descriptions and content calendars are **not implemented** — **FAIL** (gap) |
| Arabic output | `language="ar"` instructs every customer-facing field in Arabic; image prompt kept English (for the image model) | implemented; quality **BLOCKED** |
| Dialect | no dedicated dialect option; the free-text `tone` is the only lever (harness prompt mk02 tests it) | **PARTIAL** (untested) |
| Fabricated claims | two-step generation + independent factual review; sensitive Arabic/English origin, organic, medical patterns rejected unless in the source | implemented; existing unit tests pass |
| Hashtags | `#زيت زيتون` (space) tags only `#زيت` on Instagram/TikTok; duplicates and `##`/punctuation passed through | **Fixed**: `_clean_hashtags()` joins words with `_`, strips punctuation, de-duplicates (test added) |
| Review prompt | two paragraphs of the factual-review prompt were sent twice on every call | **Fixed** (duplicates removed; no wording change) |
| Real data | copy is generated only from the selected product facts and the tenant's competitor-pricing positioning label; the prompt forbids prices/discounts not supplied | verified by code + existing tests |

## 7. Image generation and Arabic typography

- **Providers: BLOCKED.** AI Horde, the HF router and Pollinations are
  unreachable from this sandbox; no Cloudflare/Together/Gemini keys exist.
  Image quality, prompt adherence and product fidelity were **not tested**.
- **Arabic inside AI images:** KEEL's image prompt already demands *no text*
  (image models do not spell Arabic reliably; a model that understands an
  Arabic prompt still draws invalid letter shapes). Until now nothing put the
  campaign's words on an AI image.
- **New typography layer** (`backend/src/ai/marketing/typography.py`):
  text-free AI background → campaign headline + CTA drawn by KEEL with libraqm
  (HarfBuzz/FriBiDi — browser-grade shaping incl. diacritic placement) and
  `direction="rtl"`; reshaper+bidi fallback without libraqm; wrapping in
  logical order; Arabic right-aligned, Latin left-aligned; legibility scrim;
  font chosen per string by glyph coverage (Noto Kufi lacks `–`, DejaVu used).
  Only the campaign's existing copy is drawn.
- **API:** `POST /marketing/campaigns/{id}/generate-image` accepts
  `"text_overlay": true` (default `false`, so existing behaviour is
  unchanged); the composed PNG is stored, added to the gallery and attached
  through the existing `image_service` path; the response reports
  `text_overlay`. A router-level test verifies the stored image keeps the AI
  background and carries the text. Gallery persistence against a real
  DB/MinIO is covered by the existing `test_marketing_image_gallery_integration_db.py`,
  which needs the isolated test stack (**NOT RUN** here).

OCR verification (each element rendered through the exact shaping path,
tesseract `ara`/`eng`, psm 7; 10 renders = 5 strings × 2 fonts):

| String | Headline CER | CTA CER |
|---|---|---|
| زيت زيتون بكر ممتاز من الندى / اطلب الآن | 0.000 | 0.000 |
| عسل سدر 500 غرام – طعم الأصالة / تسوق اليوم | 0.033 (`–` read as `-`) | 0.000 |
| خصم خاص على OL-1000 هذا الأسبوع | 0.065 (OCR LRM marks) | – |
| قهوة عربية بالهيل، رفيقة صباحك… / اكتشف المزيد | 0.017–0.035 (`،` read as `.`) | 0.000 |
| Fresh Sidr honey for Ramadan / Shop now | 0.000 | 0.000 |

Mean element CER **0.014**; residuals are OCR punctuation, verified visually.
Aspect ratios: the layer uses the image's own size, so every existing
`IMAGE_FORMATS` ratio is preserved (test asserts size unchanged).

## 8. Fixes made (before → after)

| # | Change | Files | Measured effect |
|---|---|---|---|
| 1 | Logical-order PDF text: glyph lines, marks attached, presentation forms folded, word gaps, **verified UBA inversion** with cross-line context, ruled tables per cell, two-column order, document direction from layout | `src/ai/extraction/pdf_text.py` (new), `rag/data_access.py`, `extraction/adapters/pdf_adapter.py` | Arabic PDF CER 0.60–0.91 → 0.000–0.017 |
| 2 | OCR fallback for image-only pages (tesseract `ara+eng`, psm 4, ruling removal; `PDF_OCR_ENABLED`, `PDF_OCR_LANGS`, `PDF_OCR_DPI`, `PDF_OCR_MAX_PAGES`) | `pdf_text.py` | scans: empty/Failed → CER 0.045 (prose) |
| 3 | Word tables extracted in document order | `rag/data_access.py` | contract CER 0.30 → 0.00 |
| 4 | `.txt/.md` legacy encodings (Windows-1256, UTF-16, BOM) | `rag/data_access.py` | cp1256 file: *Failed* → decoded |
| 5 | Arabic search folding in BM25 | `core/arabic_text.py` (new), `rag/bm25_index.py` | MSA hit@5 0.14 → 1.00 |
| 6 | Clitic-aware admission filter | `rag/advisor.py` | admitted hit@5 0.512 → 0.537 |
| 7 | Sales PDF: per-line shaping after logical wrapping, LTR embedding of hyphenated numbers, markup escaped | `dashboard/sales_pdf.py` | export check FAIL → PASS |
| 8 | Frontend bidi: `dir="auto"` per assistant block; `<bdi>` for product/import names | 4 components | new SSR tests pass |
| 9 | Marketing hashtags normalised; duplicate review-prompt text removed | `marketing/content_generator.py` | test added |
| 10 | Arabic typography layer + `text_overlay` option | `marketing/typography.py` (new), `marketing/image_service.py`, `routers/marketing.py` | OCR CER 0.014 |

No model was replaced; no paid service, migration or production setting was
introduced. All new behaviour is on by default only where it corrects
corrupted output (extraction, export); the image text layer is opt-in.

## 9. Tests and evidence

- New backend regressions: `backend/src/ai/tests/test_arabic_text_quality.py`
  — **18 passed** (bidi inversion over 70+ strings, KEEL-style PDF, two
  columns, PDF tables via import adapter and KB, Chromium PDF CER < 0.01,
  scanned PDF via OCR, Word tables, cp1256, BM25 folding, clitic filter,
  sales-PDF line order/date/markup, typography alignment/OCR, `text_overlay`
  API, hashtags). Chromium/tesseract cases skip when the tools are absent.
- New frontend regressions: `frontend/tests/rtlBidi.test.mjs` — **6 passed**.
  Full frontend suite: **272 passed, 0 failed**; ESLint clean on changed files.
- Full backend suite excluding live-DB modules (`--ignore-glob="*integration_db*"`):
  see §9.1. Live-DB/MinIO integration modules were **not run** (no isolated
  test stack in this sandbox; `dev.ps1 test` provides it).
- Existing focused suites re-run: RAG data access, extraction adapters, file
  dispatch, RAG advisor, marketing, content generator — all pass.

### 9.1 Full-suite comparison

Filled from the executed runs (same command on this branch and on a pristine
`HEAD` worktree):

| Tree | Passed | Failed | Skipped |
|---|---|---|---|
| pristine `HEAD` (`aaa725eb`) | 3,891 | 12 | 369 |
| this branch | 3,908 | 12 | 369 |

Command: `python -m pytest -q -rfE src/ai/tests/ src/market_scraper/tests tests --ignore-glob="*integration_db*"`
(Python 3.12.13, no database). The **12 failures are identical on both
trees** (`diff` of the failure lists is empty): 7 in
`test_notification_digest.py` and 5 in `tests/billing/` — pre-existing,
unrelated to this change, not investigated here. The +17 passes are the new
Arabic regression tests (the 18th, hashtags, was added after this run and
passes on its own).

## 10. Remaining failures and limitations

1. **Cross-language and paraphrase retrieval** (EN↔AR, synonyms, much
   Levantine) — keyword search cannot do it; the semantic tier is unmeasured
   here (**BLOCKED**).
2. **No measured answer quality, faithfulness, hallucination or citation
   correctness**, and **no measured marketing quality** (**BLOCKED**: provider
   key rejected; metering needs the DB).
3. **Scanned Arabic-Indic invoices**: digits and table rows unreliable with
   the stock tesseract model (numbers 12%) — **FAIL**.
4. LibreOffice-made PDFs keep that producer's wrong glyph mappings (CER 0.059).
5. Diacritics are not drawn in KEEL's PDF exports (arabic-reshaper removes
   harakat; ReportLab has no mark positioning).
6. Marketing lacks LinkedIn, SEO, long/short descriptions, scripts and
   content calendars; dialect is only a free-text tone.
7. The image text layer is opt-in in the API only; the Studio UI does not yet
   expose a toggle.
8. RTL e-mail/notification templates were not render-tested.
9. Benchmark documents are short (one 200-word chunk each); passage-level
   ranking is only approximated by the 40-word sensitivity run.
10. The benchmark is synthetic and built by the auditor; results on customer
    documents may differ. A held-out, independently written question set is
    needed before tuning retrieval further.

## 11. Cost and free-tier constraints

- Every fix here is local and free (pdfplumber, tesseract, Pillow/libraqm,
  rank-bm25). OCR costs ~1–3 s CPU per scanned page; `PDF_OCR_MAX_PAGES`
  (default 30) caps it per document.
- Groq: free tier/quota-limited; KEEL refuses calls without an approved cost
  schedule and available AI Credits (fail-closed, observed).
- Embeddings/re-ranker are free but memory-heavy (torch ~1.6–1.8 GB; ONNX or
  static backends documented for 512 MB hosts).
- Image providers: free daily allowances (Cloudflare/HF/Together/Gemini) or
  keyless community queues (AI Horde); the designed poster and the new text
  layer are unlimited and local.

## 12. Recommended configuration (Arabic + English)

- **Extraction:** keep the new default; install `tesseract-ocr-ara`
  (Dockerfile.ai already does). For scanned Arabic-Indic invoices, evaluate a
  vision model (KEEL already integrates `gemini-2.5-flash` for menus) or
  `tessdata_best` `ara` with this benchmark before adopting.
- **Retrieval:** `RAG_EMBEDDING_BACKEND=onnx` with
  `paraphrase-multilingual-MiniLM-L12-v2` (`onnx/model_quint8_avx2.onnx`) where
  memory allows, re-ranker on; `static` on 512 MB hosts. Re-run
  `run_benchmark.py` with the model available and compare against §4 before
  choosing; do not set `RAG_MIN_CONFIDENCE_SCORE` until calibrated.
- **LLM:** keep `openai/gpt-oss-20b` until a measured Arabic comparison exists;
  run `run_benchmark.py --llm` and `marketing_eval.py --llm` (with human
  rubric scoring) against any candidate before switching.
- **Images:** request text-free images and use `text_overlay: true` for any
  Arabic headline/CTA.

## 13. Prioritised next actions

1. Renew the expired Hugging Face token and the Groq key (environment
   secrets, not chat), then re-run `run_benchmark.py` (semantic tier) and
   `run_benchmark.py --llm` on the isolated test stack; publish the numbers here.
2. Have two Arabic-speaking reviewers score `marketing_eval.py --llm` output
   with the rubric; fix prompts only against those scores.
3. Add a Studio toggle for `text_overlay` and make it the default for Arabic
   campaigns once reviewed.
4. Benchmark a vision model / `tessdata_best` for scanned Arabic invoices.
5. Write an independent held-out Arabic question set (≥100 questions, multiple
   authors) before any retrieval tuning (dialect/synonym handling).
6. Add the missing marketing formats (LinkedIn, SEO, descriptions, calendars)
   with platform limits and tests.
7. Render-test Arabic e-mail digests; extend `<bdi>` isolation to remaining
   tables (inventory, reports, competitors) with browser screenshots.
