"""
KEEL - PDF text in Unicode LOGICAL order (Arabic, English and mixed).

Why this exists (measured, docs/ARABIC_AI_QUALITY_REPORT.md): a PDF stores
glyphs where they are DRAWN. pdfplumber/pdfminer join a line's glyphs left
to right, so an Arabic line came out with every word's letters reversed,
as presentation-form glyphs (U+FB50-FEFF, e.g. "ﺔﻛﺮﺷ" for "شركة") and with
shadda/tanween marks detached; two-column pages were read across both
columns; Chromium-made English PDFs lost every word space; scanned pages
gave no text at all. Character error rate on the benchmark's Arabic PDFs
was 0.60-0.91 - search, citations and copy/paste all saw corrupted text.

What this module does instead, per page:
1. Glyph boxes -> lines (vertical overlap), combining marks attached to the
   base letter they sit on, presentation forms folded to base letters (NFKC
   applied ONLY to those code points), word spaces from real gaps.
2. Each line's visual order -> logical order by inverting the Unicode Bidi
   Algorithm: candidate logical strings are VERIFIED by running the forward
   algorithm (python-bidi, the same UBA browsers/PDF producers apply) and
   checking it reproduces the visual line. Nothing is reversed on a guess
   when a verified reading exists.
3. Tables (pdfplumber's ruled-table finder) are read cell by cell, cells in
   logical column order (right to left for an Arabic table), one line per row.
4. Two-column body text is read column by column (right column first on an
   Arabic page).
5. A page with no text layer is OCR'd with tesseract (Arabic + English) when
   the engine is installed - the same engine and language data Dockerfile.ai
   already installs for menu pictures.

Pure function of the PDF bytes; no network.
"""
import io
import logging
import os
import re
import shutil
import unicodedata
from dataclasses import dataclass, field
from itertools import product as _product
from typing import List, Optional, Tuple

logger = logging.getLogger("CEOPRO_AI_PDF_TEXT")

PAGE_BREAK = "\f"
OCR_ENABLED = os.getenv("PDF_OCR_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")
OCR_LANGS = os.getenv("PDF_OCR_LANGS", "ara+eng")
OCR_DPI = int(os.getenv("PDF_OCR_DPI", "300"))
OCR_MAX_PAGES = int(os.getenv("PDF_OCR_MAX_PAGES", "30"))
OCR_TIMEOUT_SECONDS = int(os.getenv("PDF_OCR_TIMEOUT_SECONDS", "60"))
# A page with fewer real characters than this is treated as an image (scan).
MIN_TEXT_CHARS = 8

_PRESENTATION = re.compile("[\uFB00-\uFB06\uFB50-\uFDFF\uFE70-\uFEFF]")  # Latin + Arabic presentation forms
_CID = re.compile(r"\(cid:\d+\)")
_MIRROR = str.maketrans("()[]{}<>«»‹›", ")(][}{><»«›‹")
_LEADING_PUNCT = re.compile(r"^[.,:;!?\u060C\u061B\u061F]")
_BIDI_CONTROLS = re.compile("[\u200e\u200f\u202a-\u202e\u2066-\u2069\u061c]")


@dataclass
class _Glyph:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    size: float
    order: int
    marks: List[str] = field(default_factory=list)

    @property
    def unit(self) -> str:
        return self.text + "".join(self.marks)


def _fold(text: str) -> str:
    text = _CID.sub("", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cc")
    return _PRESENTATION.sub(lambda m: unicodedata.normalize("NFKC", m.group()), text)


def _is_mark(text: str) -> bool:
    return bool(text) and all(unicodedata.category(ch) in ("Mn", "Me") for ch in text)


def _bidi_class(unit: str) -> str:
    for ch in unit:
        if unicodedata.category(ch) in ("Mn", "Me"):
            continue
        cls = unicodedata.bidirectional(ch)
        if cls in ("R", "AL"):
            return "R"
        if cls == "L":
            return "L"
        if cls in ("EN", "AN"):
            return "N"
        return "O"  # neutral / weak separator / whitespace
    return "O"


def _strip_marks(text: str) -> str:
    return "".join(ch for ch in text if unicodedata.category(ch) not in ("Mn", "Me"))


_CONTEXT_MARK = {"L": "\u200e", "AL": "\u061c"}  # LRM / ALM: invisible strong characters


def _forward(logical: str, base: str, context: Optional[str] = None) -> str:
    """Forward UBA rendering of one line. `context` is the last strong class
    (L / AL) of the paragraph's previous line: the algorithm resolves numbers
    from it (W2/W7), so a wrapped line is verified as the renderer saw it."""
    # The pure-Python UBA: unlike python-bidi's Rust get_display it mirrors brackets
    # (rule L4), as the PDF producers' shaping engines do, so it can reproduce their output.
    from bidi.algorithm import get_display

    mark = _CONTEXT_MARK.get(context or "")
    if mark:
        return get_display(mark + logical, base_dir=base).replace(mark, "")
    return get_display(logical, base_dir=base)


def last_strong(text: str) -> Optional[str]:
    for ch in reversed(text or ""):
        cls = unicodedata.bidirectional(ch)
        if cls == "L":
            return "L"
        if cls in ("R", "AL"):
            return "AL" if cls == "AL" else None
    return None


def _ltr_spans(classes: List[str], start_cls=("L", "N"), allowed=("L", "N", "O")) -> List[Tuple[int, int]]:
    """Maximal [i, j] spans that start and end on a start_cls unit and contain only `allowed` classes."""
    spans, i, n = [], 0, len(classes)
    while i < n:
        if classes[i] in start_cls:
            j = i
            k = i + 1
            while k < n and classes[k] in allowed:
                if classes[k] in start_cls:
                    j = k
                k += 1
            spans.append((i, j))
            i = j + 1
        else:
            i += 1
    return spans


def _split_points(units: List[str], classes: List[str], span: Tuple[int, int]) -> List[int]:
    """Indexes of neutral runs inside an LTR span where it could really be two runs."""
    points, i = [], span[0]
    while i <= span[1]:
        if classes[i] == "O":
            j = i
            while j + 1 <= span[1] and classes[j + 1] == "O":
                j += 1
            points.append(i)
            i = j + 1
        else:
            i += 1
    return points


def _rtl_candidate(units: List[str], classes: List[str], spans: List[Tuple[int, int]]) -> str:
    """Reverse the run order; keep each LTR span's own order; mirror brackets outside spans."""
    pieces, i, n = [], 0, len(units)
    span_at = {s: e for s, e in spans}
    while i < n:
        if i in span_at:
            pieces.append("".join(units[i:span_at[i] + 1]))
            i = span_at[i] + 1
        else:
            unit = units[i]
            pieces.append(unit.translate(_MIRROR) if classes[i] == "O" else unit)
            i += 1
    return "".join(reversed(pieces))


def _refine(spans, cuts_per_span, choice):
    out = []
    for (start, end), cuts, chosen in zip(spans, cuts_per_span, choice):
        if not chosen:
            out.append((start, end))
            continue
        pos = start
        for cut in cuts:
            if cut in chosen:
                if pos < cut:
                    out.append((pos, cut - 1))
                pos = cut + 1
                # the neutral run between parts belongs to neither side
                while pos <= end and _CLASS_CACHE.get(pos) == "O":
                    pos += 1
        if pos <= end:
            out.append((pos, end))
    return out


_CLASS_CACHE: dict = {}


def _clean_spans(spans, classes):
    """Trim neutral edges so every span starts/ends on a strong/number unit."""
    out = []
    for start, end in spans:
        while start <= end and classes[start] == "O":
            start += 1
        while end >= start and classes[end] == "O":
            end -= 1
        if start <= end:
            out.append((start, end))
    return out


def visual_to_logical(units: List[str], base: str = "R", context: Optional[str] = None) -> str:
    """Logical text for one visual-order line (left-to-right glyph units).

    `base` is the paragraph direction to try first ("R" or "L"). Returns the
    first candidate whose forward-UBA rendering reproduces the visual line;
    the plain run-reversal candidate when none verifies."""
    if not units:
        return ""
    visual = "".join(units)
    classes = [_bidi_class(u) for u in units]
    if "R" not in classes and base == "L" and not _LEADING_PUNCT.match(visual):
        return visual  # no right-to-left text in a left-to-right line: visual order is logical order
    target = _strip_marks(visual)
    global _CLASS_CACHE
    _CLASS_CACHE = dict(enumerate(classes))

    def candidates_for(direction):
        if direction == "R":
            spans = _ltr_spans(classes)
            cuts = [_split_points(units, classes, s) for s in spans]
            options = []
            for span_cuts in cuts:
                # 2^k subsets of cut points, capped - long LTR spans are kept whole or cut everywhere.
                if len(span_cuts) <= 4:
                    subsets = [frozenset(c for c, keep in zip(span_cuts, mask) if keep)
                               for mask in _product((False, True), repeat=len(span_cuts))]
                else:
                    subsets = [frozenset(), frozenset(span_cuts)]
                options.append(subsets)
            seen = 0
            for choice in _product(*options) if options else [()]:
                seen += 1
                if seen > 256:
                    break
                refined = _clean_spans(_refine(spans, cuts, choice), classes)
                yield _rtl_candidate(units, classes, refined)
        else:
            # LTR paragraph: each right-to-left stretch is read as an RTL line of its own.
            spans = _ltr_spans(classes, start_cls=("R",), allowed=("R", "N", "O"))
            out, i = [], 0
            for start, end in spans:
                out.append("".join(units[i:start]))
                inner_units, inner_classes = units[start:end + 1], classes[start:end + 1]
                inner_spans = _clean_spans(_ltr_spans(inner_classes), inner_classes)
                out.append(_rtl_candidate(inner_units, inner_classes, inner_spans))
                i = end + 1
            out.append("".join(units[i:]))
            yield "".join(out)

    # Several readings can reproduce the same picture (a Latin sentence drawn in
    # an RTL paragraph looks identical with either paragraph direction except
    # for its final full stop). Prefer, in order: a reading verified WITH the
    # previous line's context, one that does not START with sentence
    # punctuation, then the expected paragraph direction.
    fallback, best, best_key = None, None, None
    contexts = list(dict.fromkeys((context, None)))
    for rank, direction in enumerate((base, "L" if base == "R" else "R")):
        for candidate in candidates_for(direction):
            if fallback is None:
                fallback = candidate
            for ctx_rank, ctx in enumerate(contexts):
                if _strip_marks(_forward(candidate, direction, ctx)) == target:
                    key = (ctx_rank, 1 if _LEADING_PUNCT.match(candidate) else 0, rank)
                    if best_key is None or key < best_key:
                        best, best_key = candidate, key
                    break
            if best_key == (0, 0, 0):
                return best
    return best if best is not None else fallback


# --- page geometry -------------------------------------------------------------

def _glyphs(chars) -> Tuple[List[_Glyph], List[dict]]:
    glyphs, marks = [], []
    for n, c in enumerate(chars):
        if not c.get("upright", True):
            continue
        text = _fold(c.get("text") or "")
        if not text:
            continue
        if _is_mark(text) or (c["x1"] - c["x0"] < 0.01 and _is_mark(text[:1])):
            marks.append({"text": text, "x": (c["x0"] + c["x1"]) / 2, "y": (c["top"] + c["bottom"]) / 2})
            continue
        glyphs.append(_Glyph(text, c["x0"], c["x1"], c["top"], c["bottom"], c.get("size") or (c["bottom"] - c["top"]), n))
    return glyphs, marks


def _lines(glyphs: List[_Glyph]) -> List[List[_Glyph]]:
    lines: List[List[_Glyph]] = []
    for glyph in sorted(glyphs, key=lambda g: (g.top, g.x0)):
        for line in reversed(lines[-3:]):
            ref = line[0]
            overlap = min(ref.bottom, glyph.bottom) - max(ref.top, glyph.top)
            if overlap > 0.5 * min(ref.bottom - ref.top, glyph.bottom - glyph.top):
                line.append(glyph)
                break
        else:
            lines.append([glyph])
    for line in lines:
        line.sort(key=lambda g: (round(g.x0, 1), g.order))
    return lines


def _attach_marks(lines: List[List[_Glyph]], marks: List[dict]) -> None:
    """A mark belongs to the letter whose box it sits in (the mark's origin is
    drawn inside its base glyph); on a shared edge, the nearer centre wins.
    Only letters carry marks - never a space or punctuation."""
    for mark in marks:
        best, best_key = None, None
        for line in lines:
            top, bottom = min(g.top for g in line), max(g.bottom for g in line)
            size = max(g.size for g in line)
            if not (top - 0.6 * size <= mark["y"] <= bottom + 0.6 * size):
                continue
            for glyph in line:
                if _bidi_class(glyph.text) not in ("R", "L"):
                    continue
                inside = glyph.x0 <= mark["x"] < glyph.x1
                edge = 0.0 if inside else min(abs(mark["x"] - glyph.x0), abs(mark["x"] - glyph.x1))
                key = (0 if inside else 1, edge, abs(mark["x"] - (glyph.x0 + glyph.x1) / 2))
                if best_key is None or key < best_key:
                    best, best_key = glyph, key
        if best is not None and best_key[1] < 6:
            best.marks.append(mark["text"])


def _units(line: List[_Glyph]) -> List[str]:
    """Glyph units left to right, with a space wherever the gap is a word gap."""
    units, previous = [], None
    for glyph in line:
        if glyph.text.isspace():
            if units and units[-1] != " ":
                units.append(" ")
            previous = glyph
            continue
        if previous is not None and not previous.text.isspace():
            gap = glyph.x0 - previous.x1
            if gap > 0.2 * max(glyph.size, previous.size) and units and units[-1] != " ":
                units.append(" ")
        units.append(glyph.unit)
        previous = glyph
    while units and units[0] == " ":
        units.pop(0)
    while units and units[-1] == " ":
        units.pop()
    return units


def _arabic_majority(glyphs: List[_Glyph]) -> bool:
    arabic = sum(1 for g in glyphs if _bidi_class(g.text) == "R")
    latin = sum(1 for g in glyphs if _bidi_class(g.text) == "L")
    return arabic >= latin and arabic > 0


def _line_base(line: List[_Glyph], page_rtl: bool) -> str:
    arabic = sum(1 for g in line if _bidi_class(g.text) == "R")
    latin = sum(1 for g in line if _bidi_class(g.text) == "L")
    if arabic > latin:
        return "R"
    if latin > arabic:
        return "L"
    return "R" if page_rtl else "L"


def _line_text(line: List[_Glyph], page_rtl: bool, context: Optional[str] = None) -> str:
    # On a right-to-left page every line is first read as an RTL paragraph line
    # (a Latin sentence there is drawn with its full stop at the far left);
    # verification and the leading-punctuation rule pick the other reading
    # when that is the one that reproduces the line.
    return visual_to_logical(_units(line), "R" if page_rtl else _line_base(line, page_rtl), context)


def _lines_text(lines: List[List[_Glyph]], page_rtl: bool) -> List[str]:
    """Each line's text, verified with the strong-character context of the
    previous line of the same paragraph (baselines closer than 2.1 glyph heights)."""
    out, previous_text, previous_line = [], None, None
    for line in lines:
        context = None
        if previous_line is not None and previous_text:
            height = max(g.bottom - g.top for g in previous_line)
            if 0 <= min(g.top for g in line) - min(g.top for g in previous_line) <= 2.1 * height:
                context = last_strong(previous_text)
        text = _line_text(line, page_rtl, context)
        out.append(text)
        previous_text, previous_line = text, line
    return out


def _split_columns(lines: List[List[_Glyph]], x_min: float, x_max: float) -> Optional[float]:
    """The x of one vertical gutter shared by several lines (two-column body text), or None."""
    width = x_max - x_min
    if width <= 0 or len(lines) < 4:
        return None
    candidates = {}
    for line in lines:
        size = max(g.size for g in line)
        solid = [g for g in line if not g.text.isspace()]
        for a, b in zip(solid, solid[1:]):
            gap = b.x0 - a.x1
            mid = (a.x1 + b.x0) / 2
            if gap > 2.0 * size and x_min + 0.25 * width < mid < x_min + 0.75 * width:
                key = round(mid / 10)
                candidates[key] = candidates.get(key, 0) + 1
    if not candidates:
        return None
    key, count = max(candidates.items(), key=lambda kv: kv[1])
    if count < 3:
        return None
    gutter = key * 10.0
    crossing = sum(1 for line in lines if _crosses(line, gutter))
    return gutter if crossing <= max(2, 0.2 * len(lines)) else None


def _crosses(line: List[_Glyph], gutter: float) -> bool:
    """True when the line's text runs across the gutter (a full-width line, e.g. a title)."""
    size = max(g.size for g in line)
    solid = [g for g in line if not g.text.isspace()]
    left = [g for g in solid if g.x1 <= gutter + 1]
    right = [g for g in solid if g.x1 > gutter + 1]
    if not left or not right:
        return False
    return min(g.x0 for g in right) - max(g.x1 for g in left) < 1.5 * size


def _strip_spaces(part: List[_Glyph]) -> List[_Glyph]:
    while part and part[0].text.isspace():
        part = part[1:]
    while part and part[-1].text.isspace():
        part = part[:-1]
    return part


def _table_lines(page, table, page_rtl: bool) -> List[str]:
    rows = table_rows(page, table, page_rtl)
    return ["\t".join(cell for cell in row) for row in rows]


def table_rows(page, table, page_rtl: Optional[bool] = None) -> List[List[str]]:
    """Rows of one pdfplumber table as logical-order cell strings, columns in reading order."""
    glyphs, marks = _glyphs(page.chars)
    if page_rtl is None:
        page_rtl = _arabic_majority(glyphs)
    rows = []
    for row in table.rows:
        cells = []
        for bbox in row.cells:
            if bbox is None:
                cells.append("")
                continue
            x0, top, x1, bottom = bbox
            inside = [g for g in glyphs if g.x0 >= x0 - 1 and g.x1 <= x1 + 1 and g.top >= top - 1 and g.bottom <= bottom + 1]
            cell_marks = [mk for mk in marks if x0 - 1 <= mk["x"] <= x1 + 1 and top - 1 <= mk["y"] <= bottom + 1]
            lines = _lines([_Glyph(g.text, g.x0, g.x1, g.top, g.bottom, g.size, g.order) for g in inside])
            _attach_marks(lines, cell_marks)
            cells.append(" ".join(_line_text(line, page_rtl) for line in lines).strip())
        rows.append(cells)
    if rows and _table_is_rtl(rows):
        rows = [list(reversed(r)) for r in rows]
    return rows


def _table_is_rtl(rows: List[List[str]]) -> bool:
    text = " ".join(" ".join(r) for r in rows)
    arabic = sum(1 for ch in text if _bidi_class(ch) == "R")
    latin = sum(1 for ch in text if _bidi_class(ch) == "L")
    return arabic > latin


def find_tables(page):
    try:
        return [t for t in page.find_tables() if len(t.rows) >= 2]
    except Exception:  # noqa: BLE001 - a table-finder failure leaves plain text
        return []


def page_text(page, rtl: Optional[bool] = None) -> str:
    """One page's text in logical reading order ('' when it has no text layer).
    `rtl`: the document's direction (Arabic majority), else this page's own."""
    glyphs, marks = _glyphs(page.chars)
    if not glyphs:
        return ""
    page_rtl = _arabic_majority(glyphs) if rtl is None else rtl
    tables = find_tables(page)
    blocks = []  # (top, text)
    in_table = set()
    for table in tables:
        x0, top, x1, bottom = table.bbox
        for i, g in enumerate(glyphs):
            if g.x0 >= x0 - 1 and g.x1 <= x1 + 1 and g.top >= top - 1 and g.bottom <= bottom + 1:
                in_table.add(i)
        blocks.append((top, "\n".join(_table_lines(page, table, page_rtl))))
    body = [g for i, g in enumerate(glyphs) if i not in in_table]
    lines = _lines(body)
    _attach_marks(lines, marks)
    if lines:
        x_min, x_max = min(g.x0 for g in body), max(g.x1 for g in body)
        gutter = _split_columns(lines, x_min, x_max)
        if gutter is None:
            blocks.extend(zip((line[0].top for line in lines), _lines_text(lines, page_rtl)))
        else:
            run: List[Tuple[float, List[_Glyph], List[_Glyph]]] = []

            def flush():
                if not run:
                    return
                lefts, rights = [l for _, l, _ in run], [r for _, _, r in run]
                first, second = (rights, lefts) if page_rtl else (lefts, rights)
                text = "\n".join(_lines_text([p for p in first if p], page_rtl) + _lines_text([p for p in second if p], page_rtl))
                blocks.append((run[0][0], text))
                run.clear()

            for line in lines:
                if _crosses(line, gutter):
                    flush()
                    blocks.append((line[0].top, _line_text(line, page_rtl)))
                    continue
                left = [g for g in line if g.x1 <= gutter + 1]
                right = [g for g in line if g.x1 > gutter + 1]
                run.append((line[0].top, _strip_spaces(left), _strip_spaces(right)))
            flush()
    blocks.sort(key=lambda b: b[0])
    text = "\n".join(t for _, t in blocks if t)
    return _BIDI_CONTROLS.sub("", text)


# --- OCR -------------------------------------------------------------------------

def ocr_available() -> bool:
    if not OCR_ENABLED or shutil.which("tesseract") is None:
        return False
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return True


_LANGS: Optional[str] = None


def _ocr_langs() -> str:
    global _LANGS
    if _LANGS is None:
        try:
            import pytesseract

            installed = set(pytesseract.get_languages(config=""))
            wanted = [lang for lang in OCR_LANGS.split("+") if lang in installed]
            _LANGS = "+".join(wanted) or "eng"
        except Exception:  # noqa: BLE001
            _LANGS = "eng"
    return _LANGS


def _remove_rulings(image):
    """Whitens table rulings (long horizontal / vertical dark runs): tesseract
    reads ruled table rows as noise or drops them (measured on the benchmark's
    scanned invoice: CER 0.60 -> 0.44 with rulings removed)."""
    import numpy as np
    from PIL import Image

    pixels = np.asarray(image).copy()
    dark = pixels < 128
    height, width = pixels.shape
    pixels[dark.mean(axis=1) > 0.3] = 255
    for x in np.where(dark.sum(axis=0) > 0.04 * height)[0]:
        column = np.concatenate([[0], dark[:, x].astype(np.int8), [0]])
        edges = np.diff(column)
        for start, end in zip(np.where(edges == 1)[0], np.where(edges == -1)[0]):
            if end - start > 0.04 * height:
                pixels[start:end, x] = 255
    return Image.fromarray(pixels)


def ocr_page(page) -> str:
    """Tesseract on the rendered page, logical-order Unicode ('' on failure)."""
    import pytesseract
    from PIL import ImageOps

    try:
        image = ImageOps.autocontrast(page.to_image(resolution=OCR_DPI).original.convert("L"))
        image = _remove_rulings(image)
        # psm 4 (one column of variable-size text) measured best on Arabic pages.
        text = pytesseract.image_to_string(image, lang=_ocr_langs(), config="--psm 4", timeout=OCR_TIMEOUT_SECONDS)
    except Exception:  # noqa: BLE001 - one unreadable page never fails the document
        logger.warning("OCR failed for one PDF page", exc_info=True)
        return ""
    text = _BIDI_CONTROLS.sub("", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def document_is_rtl(pdf) -> Optional[bool]:
    """The document's paragraph direction (None when no page has a text layer).

    Decided from layout first: a paragraph's short last line sits flush with
    the right margin in a right-to-left document and the left margin in a
    left-to-right one, whatever script its words are in (an Arabic report
    quoting English sentences is still RTL). Letter counts decide only when
    the layout has too few short lines to tell."""
    arabic = latin = flush_right = flush_left = 0
    for page in pdf.pages[:OCR_MAX_PAGES]:
        glyphs, _ = _glyphs(getattr(page, "chars", None) or [])
        for g in glyphs:
            cls = _bidi_class(g.text)
            arabic += cls == "R"
            latin += cls == "L"
        solid = [g for g in glyphs if not g.text.isspace()]
        if not solid:
            continue
        left, right = min(g.x0 for g in solid), max(g.x1 for g in solid)
        width = right - left
        for line in _lines(solid):
            x0, x1 = min(g.x0 for g in line), max(g.x1 for g in line)
            if width <= 0 or x1 - x0 > 0.8 * width:
                continue
            size = max(g.size for g in line)
            if right - x1 < size and x0 - left > 2 * size:
                flush_right += 1
            elif x0 - left < size and right - x1 > 2 * size:
                flush_left += 1
    if not arabic and not latin:
        return None
    if arabic and flush_right + flush_left >= 2 and max(flush_right, flush_left) >= 2 * min(flush_right, flush_left):
        return flush_right > flush_left
    return arabic >= latin


def extract_text(raw: bytes, ocr: Optional[bool] = None) -> Tuple[str, dict]:
    """(page texts joined by form feeds, stats). Blank pages keep their place."""
    import pdfplumber

    use_ocr = ocr_available() if ocr is None else (ocr and ocr_available())
    pages, ocr_pages = [], 0
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        rtl = document_is_rtl(pdf)
        for number, page in enumerate(pdf.pages):
            try:
                # An object without glyph boxes (a stand-in page) only offers plain text.
                text = page_text(page, rtl) if hasattr(page, "chars") else _fold(page.extract_text() or "")
            except Exception:  # noqa: BLE001 - fall back to the library's own reading for this page
                logger.warning("logical-order extraction failed for one page; using plain extraction", exc_info=True)
                text = _fold(page.extract_text() or "")
            if len(text.replace(" ", "").replace("\n", "")) < MIN_TEXT_CHARS and use_ocr and ocr_pages < OCR_MAX_PAGES:
                ocr_text = ocr_page(page)
                if ocr_text:
                    text, ocr_pages = ocr_text, ocr_pages + 1
            pages.append(text)
    return PAGE_BREAK.join(pages), {"pages": len(pages), "ocr_pages": ocr_pages}
