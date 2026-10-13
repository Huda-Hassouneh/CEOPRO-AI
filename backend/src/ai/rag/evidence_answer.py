"""
Evidence mode: what the assistant shows when the language model can't
answer (no provider configured, provider down or rate limited).

Everything the assistant would have given the model is real and already
computed for this question - retrieved document passages, the
question-specific analysis (restock, trends, competitor comparison) and
the product's own how-to directions. Instead of a bare "the assistant is
unavailable", the user gets that material directly, clearly labelled as
unsummarised evidence. Nothing here is generated or paraphrased.

Generic company facts written for the model (they cite database tables)
are deliberately left out: they only make sense as model input.
"""
import re
from typing import List, Optional

_SOURCE_SPLIT = re.compile(r"\[Source (\d+)\]\s*\n")
_MAX_PASSAGES = 3
_MAX_PASSAGE_CHARS = 700
_MAX_BLOCK_CHARS = 2500
# Generated documents written as guidance for the model, not the company's
# own information - never shown as evidence.
_MODEL_ONLY_SUMMARIES = {"platform_help.txt", "pos_erp_systems.txt", "troubleshooting_help.txt"}

_LEAD = {
    "en": {
        "not_configured": "The AI writer isn't set up on this server, so here is what KEEL found for your question, without a written summary:",
        "provider_busy": "The AI writer is busy right now, so here is what KEEL found for your question, without a written summary:",
        "provider_unavailable": "The AI writer is temporarily unavailable, so here is what KEEL found for your question, without a written summary:",
    },
    "ar": {
        "not_configured": "خدمة الكتابة بالذكاء الاصطناعي غير مُعدّة على هذا الخادم، وهذه المعلومات التي وجدها KEEL لسؤالك دون ملخص مكتوب:",
        "provider_busy": "خدمة الكتابة بالذكاء الاصطناعي مشغولة الآن، وهذه المعلومات التي وجدها KEEL لسؤالك دون ملخص مكتوب:",
        "provider_unavailable": "خدمة الكتابة بالذكاء الاصطناعي غير متاحة مؤقتًا، وهذه المعلومات التي وجدها KEEL لسؤالك دون ملخص مكتوب:",
    },
}
_HEADINGS = {
    "en": {"guide": "How to do it in KEEL", "analysis": "From your data", "documents": "From your documents", "summary": "KEEL summary of your data"},
    "ar": {"guide": "طريقة القيام بذلك في KEEL", "analysis": "من بياناتك", "documents": "من مستنداتك", "summary": "ملخص KEEL لبياناتك"},
}


def _trim(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " …"


def _passages(context_text: str) -> dict:
    parts = _SOURCE_SPLIT.split(context_text or "")
    # ["", "1", "text", "2", "text", ...]
    return {int(parts[i]): parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}


def _document_names(conn, tenant_id: str, chunk_ids: List[str]) -> dict:
    if conn is None or not chunk_ids:
        return {}
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.chunk_id::text, m.file_name, m.storage_bucket_path
            FROM rag_document_chunks c
            JOIN rag_documents_metadata m ON m.document_id = c.document_id AND m.tenant_id = c.tenant_id
            WHERE c.tenant_id = %s AND c.chunk_id::text = ANY(%s);
            """,
            (tenant_id, chunk_ids),
        )
        return {row[0]: (row[1], row[2]) for row in cursor.fetchall()}


def _guide_lines(guide_block: str) -> List[str]:
    return [line[2:].strip() for line in (guide_block or "").splitlines() if line.startswith("- ")]


def _analysis_text(text: str) -> str:
    return _trim(text, _MAX_BLOCK_CHARS)


_WORD = re.compile(r"[\w\u0600-\u06FF]+", re.UNICODE)
_STOP = {
    "what", "which", "where", "when", "with", "this", "that", "have", "does", "about", "from", "your", "were",
    "need", "show", "tell", "much", "many", "they", "them", "there", "their", "into", "last", "next", "month",
    "week", "year", "today", "should", "could", "would", "please", "ماذا", "كيف", "هل", "متى", "أين", "التي", "الذي",
    # Words every business document contains - matching on them alone is noise.
    "product", "products", "item", "items", "sales", "sell", "selling", "business", "company", "customer", "customers",
    "منتج", "منتجات", "المنتجات", "مبيعات", "المبيعات", "شركة", "عملاء",
}


def _stems(text: str) -> set:
    """Lower-cased 4-letter prefixes of the meaningful words - crude, but
    enough to tell a passage that shares the question's subject from one
    that only matched on noise."""
    return {w.lower()[:4] for w in _WORD.findall(text or "") if len(w) >= 4 and w.lower() not in _STOP}


_SALES_WORDS = ("sale", "sold", "revenue", "income", "turnover", "مبيع", "إيراد", "ايراد", "دخل")
_SECTION_SOURCE = re.compile(r"\s*\(source:[^)]*\)")


def _sales_summary(structured_facts: str, question: str) -> List[str]:
    """The live sales lines from the company facts, with the model-facing
    source notes removed - only for questions about sales."""
    q = (question or "").lower()
    if not structured_facts or not any(word in q for word in _SALES_WORDS):
        return []
    keep, out = False, []
    for line in structured_facts.splitlines():
        if not line.startswith("-"):
            keep = line.startswith(("Sales in the last", "Top products by revenue"))
            if keep:
                out.append(_SECTION_SOURCE.sub("", line))
        elif keep:
            out.append(line)
    return out


def build_evidence_answer(
    conn, tenant_id: str, context, analysis_blocks: list, guide_block: str,
    language: str, reason: str, structured_facts: str = "",
) -> Optional[dict]:
    """Returns {"answer", "evidence"} or None when there is nothing real to
    show (the caller then reports the provider problem as before)."""
    lang = "ar" if language == "ar" else "en"
    headings = _HEADINGS[lang]

    guide = _guide_lines(guide_block)
    analysis = [_analysis_text(text) for _label, text in (analysis_blocks or []) if text and text.strip()]
    sales = [] if guide else _sales_summary(structured_facts, getattr(context, "query", ""))
    if sales:
        analysis.insert(0, "\n".join(sales))
    question_stems = _stems(getattr(context, "query", ""))

    passages_by_index = _passages(getattr(context, "context_text", ""))
    sources = [s for s in (getattr(context, "sources", None) or []) if s.get("chunk_id")]
    names = _document_names(conn, tenant_id, [str(s["chunk_id"]) for s in sources])
    documents = []
    for source in sources:
        text = passages_by_index.get(source.get("source_index"))
        if not text or not (question_stems & _stems(text)):
            continue  # nothing in common with the question: retrieval noise
        file_name, path = names.get(str(source["chunk_id"]), (None, ""))
        generated = (path or "").startswith("_generated/")
        if generated and (file_name in _MODEL_ONLY_SUMMARIES or analysis):
            # Help text for the model, or a broad data summary when the
            # question-specific analysis already answers more precisely.
            continue
        documents.append({
            "document": headings["summary"] if generated else (file_name or headings["documents"]),
            "generated": generated,
            "text": _trim(text, _MAX_PASSAGE_CHARS),
        })
        if len(documents) >= _MAX_PASSAGES:
            break

    if not (guide or analysis or documents):
        return None

    lines = [_LEAD[lang].get(reason, _LEAD[lang]["provider_unavailable"])]
    if guide:
        lines += ["", f"{headings['guide']}:"] + [f"- {item}" for item in guide]
    if analysis:
        lines += ["", f"{headings['analysis']}:"] + analysis
    if documents:
        lines += ["", f"{headings['documents']}:"]
        lines += [f"[{doc['document']}] {doc['text']}" for doc in documents]
    return {
        "answer": "\n".join(lines),
        "evidence": {"reason": reason, "guide": guide, "analysis": analysis, "documents": documents},
    }
