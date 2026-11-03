"""
Scoring for the Arabic benchmark. Pure Python, no third-party dependency.

Normalisation is deliberately MINIMAL for CER/WER: only whitespace is
collapsed (and the page-break form feed treated as whitespace). Presentation
forms, reversed letters, lost diacritics and wrong digits all count as
errors - they are what a customer's search, citation or copy/paste sees.

`search_norm()` is the separate, lenient normalisation used only to decide
whether a fact/passage is *findable* (digits unified, diacritics/tatweel and
alef/yaa/taa-marbuta variants folded, lower case) - the same folding KEEL's
own question understanding applies (rag/understanding.py::_norm).
"""
import re
import unicodedata
from collections import Counter
from typing import Dict, List, Sequence

_WS = re.compile(r"\s+")
_ARABIC_LETTER = re.compile(r"[ء-يٱ-ۓ]")
_PRESENTATION = re.compile(r"[\ufb50-\ufdff\ufe70-\ufeff]")
_DIACRITICS = re.compile(r"[\u064b-\u0652\u0670ـ]")
_INDIC = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def ws(text: str) -> str:
    return _WS.sub(" ", text or "").strip()


def search_norm(text: str) -> str:
    text = (text or "").translate(_INDIC).replace("٫", ".").replace("٬", ",").replace("٪", "%").lower()
    text = _DIACRITICS.sub("", text)
    text = text.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"}))
    return ws(text)


def levenshtein(a: Sequence, b: Sequence) -> int:
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def cer(reference: str, hypothesis: str) -> float:
    ref, hyp = ws(reference), ws(hypothesis)
    return levenshtein(ref, hyp) / max(1, len(ref))


def wer(reference: str, hypothesis: str) -> float:
    ref, hyp = ws(reference).split(), ws(hypothesis).split()
    return levenshtein(ref, hyp) / max(1, len(ref))


def word_stats(reference: str, hypothesis: str) -> Dict[str, float]:
    """Missing / duplicated / reversed word rates (bag of words)."""
    ref, hyp = Counter(ws(reference).split()), Counter(ws(hypothesis).split())
    ref_total, hyp_total = sum(ref.values()), sum(hyp.values())
    missing = sum((ref - hyp).values())
    duplicated = sum(max(0, hyp[w] - ref[w]) for w in hyp if w in ref)
    arabic_hyp = [w for w in hyp.elements() if _ARABIC_LETTER.search(w)]
    reversed_words = sum(1 for w in arabic_hyp if w not in ref and w[::-1] in ref and w != w[::-1])
    return {
        "missing_word_rate": missing / max(1, ref_total),
        "duplicated_word_rate": duplicated / max(1, hyp_total),
        "reversed_arabic_word_rate": reversed_words / max(1, len(arabic_hyp)),
    }


def arabic_preservation(reference: str, hypothesis: str) -> Dict[str, float]:
    """Share of the reference's Arabic letters present (multiset) as base
    Unicode letters, and how many presentation-form glyphs leaked through."""
    ref = Counter(_ARABIC_LETTER.findall(reference))
    hyp = Counter(_ARABIC_LETTER.findall(hypothesis))
    kept = sum((ref & hyp).values())
    return {
        "arabic_letter_recall": kept / max(1, sum(ref.values())),
        "presentation_form_chars": len(_PRESENTATION.findall(hypothesis)),
        "diacritic_recall": _ratio(len(_DIACRITICS.findall(hypothesis.replace("ـ", ""))),
                                   len(_DIACRITICS.findall(reference.replace("ـ", "")))),
    }


def _ratio(found: int, expected: int) -> float:
    return 1.0 if expected == 0 else min(1.0, found / expected)


def numeric_accuracy(numbers: List[str], hypothesis: str) -> float:
    """Share of expected values findable in the (digit-normalised) text, as
    exact tokens (so '5' does not match inside '15')."""
    hyp = search_norm(hypothesis)
    found = 0
    for value in numbers:
        if re.search(r"(?<![\d.,/])" + re.escape(search_norm(value)) + r"(?![\d])", hyp):
            found += 1
    return found / max(1, len(numbers))


def _locate(passage: str, hypothesis: str):
    """Position of a passage in the text, by its best-matching distinctive
    8-word shingle; None if under half of the passage's words are found."""
    words = search_norm(passage).split()
    hyp = search_norm(hypothesis)
    if not words:
        return None
    best = None
    size = min(4, len(words))
    for start in range(0, len(words) - size + 1):
        shingle = " ".join(words[start:start + size])
        index = hyp.find(shingle)
        if index >= 0:
            best = index - len(" ".join(words[:start]))
            break
    hyp_words = set(hyp.split())
    if best is None or sum(w in hyp_words for w in words) < len(words) / 2:
        return None
    return best


def reading_order(paragraphs: List[str], hypothesis: str) -> Dict[str, float]:
    """Paragraph-level reading order: of the adjacent reference paragraph
    pairs that are both located, the share appearing in the right order."""
    positions = [_locate(p, hypothesis) for p in paragraphs]
    located = [p for p in positions if p is not None]
    pairs = [(a, b) for a, b in zip(positions, positions[1:]) if a is not None and b is not None]
    return {
        "paragraphs_located": len(located) / max(1, len(paragraphs)),
        "reading_order_accuracy": (sum(a < b for a, b in pairs) / len(pairs)) if pairs else 0.0,
    }


def field_accuracy(fields: Dict[str, str], labels: Dict[str, str], hypothesis: str) -> float:
    """A field is correct when its exact (normalised) value is on the same
    line as its label."""
    lines = [search_norm(line) for line in (hypothesis or "").splitlines()]
    ok = 0
    for key, value in fields.items():
        label, want = search_norm(labels[key]), search_norm(value)
        ok += any(label in line and want in line for line in lines)
    return ok / max(1, len(fields))


def table_row_accuracy(rows: List[List[str]], hypothesis: str) -> float:
    """A row is correct when every one of its cells appears, exactly, on one
    line of the text (cells of a row kept together)."""
    lines = [search_norm(line) for line in (hypothesis or "").splitlines()]
    ok = 0
    for row in rows:
        cells = [search_norm(str(c)) for c in row]
        ok += any(all(cell in line for cell in cells) for line in lines)
    return ok / max(1, len(rows))


# --- retrieval -----------------------------------------------------------------

def precision_at_k(relevant: List[bool], k: int) -> float:
    return sum(relevant[:k]) / k


def recall_at_k(relevant: List[bool], k: int, total_relevant: int) -> float:
    return (sum(relevant[:k]) / total_relevant) if total_relevant else 0.0


def hit_at_k(relevant: List[bool], k: int) -> float:
    return 1.0 if any(relevant[:k]) else 0.0


def mrr(relevant: List[bool]) -> float:
    for rank, rel in enumerate(relevant, 1):
        if rel:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(relevant: List[bool], k: int, total_relevant: int) -> float:
    import math

    dcg = sum(1.0 / math.log2(rank + 1) for rank, rel in enumerate(relevant[:k], 1) if rel)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(k, total_relevant) + 1))
    return dcg / ideal if ideal else 0.0


def nfkc_presentation(text: str) -> str:
    """Only for diagnostics: what the text would be if presentation forms were folded."""
    return _PRESENTATION.sub(lambda m: unicodedata.normalize("NFKC", m.group()), text)
