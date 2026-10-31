"""
Menus and price lists that are published as pictures or PDFs.

Many restaurants, salons and clinics put their prices in a menu photo or a
PDF, which the page-text reader (intel.py) cannot see. This module finds
those files on the competitor's own pages, reads their text (a PDF's text
layer, or OCR for a picture / scanned PDF) and hands the lines to the same
price parser the page text uses, so the result lands in the same tables.

Honest limits, kept visible to the owner:
- OCR is weaker evidence than a site's structured data, so facts from it
  carry a lower confidence and are tagged extracted_by="ocr" with the file
  they came from; the owner can verify against the source.
- A price that ALSO appears (same name, same amount) in the page text or
  structured data corroborates it: the stronger fact gains confidence and
  records the media file as a second source.
- Without the OCR engine installed (tesseract) pictures are skipped and the
  result says so (ocr_available=False) rather than pretending nothing was
  there. PDFs with a text layer still work.

Nothing here fetches on its own: the caller supplies bytes, so the same
robots.txt, public-address and size rules as the page reader apply.
"""
import base64
import io
import logging
import os
import re
import shutil
from difflib import SequenceMatcher
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import unquote, urljoin, urlsplit
from src.ai.core.env_secret import secret

logger = logging.getLogger("KEEL_MARKET_DISCOVERY")

MEDIA_MAX_BYTES = int(os.getenv("DISCOVERY_MENU_MEDIA_MAX_BYTES", str(8_000_000)))
MAX_MEDIA_FILES = int(os.getenv("DISCOVERY_MENU_MEDIA_MAX_FILES", "6"))
MAX_PDF_PAGES = int(os.getenv("DISCOVERY_MENU_MEDIA_MAX_PDF_PAGES", "8"))
MAX_IMAGE_PIXELS = 25_000_000  # a decoded picture is ~4 bytes a pixel, and several sites are read in parallel
# Wall-clock budget for all menu files of one site: tesseract can take ~45 s on a bad picture, so without a cap
# 15 files could hold a worker for ten minutes.
TIME_BUDGET_SECONDS = float(os.getenv("DISCOVERY_MENU_MEDIA_BUDGET_SECONDS", "90"))
OCR_LANGS = os.getenv("DISCOVERY_OCR_LANGS", "ara+eng")
MIN_OCR_WIDTH = 1600  # smaller pictures are upscaled; tesseract needs ~300 dpi text

# Vision-model reading of stylised menus tesseract cannot read (V8): off unless an operator turns it on, and paid
# per call from the company's Data Credits (refused until the provider has a price - provider_billing.py).
#   off       never (default)
#   fallback  only for a picture tesseract missing/failed to get prices from
#   always    every menu picture and scanned page
VISION_MODE = os.getenv("DISCOVERY_VISION_OCR", "off").lower()
VISION_MAX_FILES = int(os.getenv("DISCOVERY_VISION_MAX_FILES", "3"))
VISION_MODEL = os.getenv("DISCOVERY_VISION_MODEL", "gemini-2.5-flash")
VISION_URL = os.getenv("GEMINI_VISION_URL", "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent")
# Which vision model reads the pictures: gemini (GEMINI_API_KEYS) or groq (GROQ_API_KEY, an OpenAI-compatible vision
# model). auto = Gemini when its key is set, otherwise Groq. Both are metered the same way (provider_billing.py).
VISION_PROVIDER = os.getenv("DISCOVERY_VISION_PROVIDER", "gemini").lower()
GROQ_VISION_MODEL = os.getenv("DISCOVERY_GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
GROQ_VISION_URL = os.getenv("GROQ_VISION_URL", "https://api.groq.com/openai/v1/chat/completions")
VISION_MAX_SIDE = 2000
VISION_PROMPT = ("This is a picture of a menu or price list. Transcribe every item that has a price, one per line, as "
                 "`item name  price currency` exactly as printed (keep Arabic and English as written; keep the printed "
                 "currency word or symbol). Include size variants as separate lines. Do not add, translate, guess or "
                 "correct anything. Skip headings and anything without a price. If there is no menu, answer with nothing.")

CONFIDENCE_PDF_TEXT = 0.7
CONFIDENCE_VISION = 0.55
CONFIDENCE_OCR = 0.5
CONFIDENCE_OCR_NO_CURRENCY = 0.4
CONFIDENCE_CORROBORATED_BONUS = 0.05

_MENU_WORDS = re.compile(r"menu|price|prices|pricing|pricelist|price-list|rates|tariff|catalog|catalogue|brochure|offer|"
                         r"منيو|المنيو|قائمة|قايمة|الأسعار|اسعار|أسعار|الوجبات|كتالوج", re.IGNORECASE)
_NOT_MENU = re.compile(r"logo|icon|sprite|avatar|favicon|banner|hero|slider|thumb|flag|badge|payment|visa|mastercard|"
                       r"facebook|instagram|twitter|whatsapp|tripadvisor|map|qr|arrow|loading|placeholder|pixel", re.IGNORECASE)
_IMG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_ATTR = r"""\b{name}\s*=\s*(?:"([^"]*)"|'([^']*)')"""
_ANCHOR = re.compile(r"<a\s[^>]*href\s*=\s*[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_IMAGE_EXT = re.compile(r"\.(jpe?g|png|webp)(\?.*)?$", re.IGNORECASE)
_PDF_EXT = re.compile(r"\.pdf(\?.*)?$", re.IGNORECASE)
# Digits OCR confuses inside a number: O->0, l/I/|->1, S->5, B->8 (only when the token is otherwise a number).
_NUMBERISH = re.compile(r"(?<![A-Za-z؀-ۿ])[0-9OoIl|SB][0-9OoIl|SB]*[.,][0-9OoIl|SB]{1,3}(?![A-Za-z؀-ۿ])")
_OCR_DIGIT = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "|": "1", "S": "5", "B": "8"})


def _attr(tag: str, name: str) -> str:
    match = re.search(_ATTR.format(name=name), tag, re.IGNORECASE)
    return (match.group(1) or match.group(2) or "").strip() if match else ""


def _score(url: str, label: str) -> int:
    name = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
    if _NOT_MENU.search(name) and not _MENU_WORDS.search(label):
        return 0
    return 2 * bool(_MENU_WORDS.search(name)) + 2 * bool(_MENU_WORDS.search(label))


def media_links(html: str, page_url: str, menu_page: bool = False,
                same_site: Optional[Callable[[str, str], bool]] = None, limit: int = MAX_MEDIA_FILES) -> List[str]:
    """Menu-looking PDFs and pictures on one page, best first. A PDF link
    counts when it (or its link text) says menu/price, or when the page is a
    menu page; a picture needs a menu word in its file name / alt text, or to
    sit on a menu page and not look like a logo or icon."""
    scored: Dict[str, int] = {}

    def add(raw: str, label: str, kind: str) -> None:
        if not raw or raw.startswith("data:"):
            return
        url = urljoin(page_url, raw.split()[0].split(",")[0])
        if urlsplit(url).scheme not in ("http", "https"):
            return
        if same_site is not None and not same_site(url, page_url):
            return
        points = _score(url, label)
        if kind == "pdf":
            points = points or (1 if menu_page else 0)
        else:
            if _NOT_MENU.search(unquote(urlsplit(url).path.rsplit("/", 1)[-1])) and not points:
                return
            points = points or (1 if menu_page else 0)
        if points:
            scored[url] = max(scored.get(url, 0), points)

    for match in _ANCHOR.finditer(html):
        href, inner = match.group(1), _TAG.sub(" ", match.group(2))
        if _PDF_EXT.search(href):
            add(href, inner, "pdf")
        elif _IMAGE_EXT.search(href):
            add(href, inner, "image")
    for tag in _IMG.findall(html):
        source = _attr(tag, "data-src") or _attr(tag, "data-lazy-src") or _attr(tag, "src")
        srcset = _attr(tag, "srcset")
        if srcset and not source:
            source = srcset.split(",")[-1].strip().split(" ")[0]  # the widest candidate
        if source and _IMAGE_EXT.search(source):
            add(source, _attr(tag, "alt") + " " + _attr(tag, "title"), "image")
    ranked = sorted(scored, key=lambda url: (-scored[url], url))
    return ranked[:limit]


# --- reading -----------------------------------------------------------------

def sniff(data: bytes, content_type: str = "") -> Optional[str]:
    """'pdf' | 'image' | None, from the file's own bytes first."""
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n" or (data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
        return "image"
    return None


_TESSERACT_LANGS: Optional[List[str]] = None


def ocr_available() -> bool:
    if shutil.which("tesseract") is None:
        return False
    try:
        import pytesseract  # noqa: F401
        return True
    except ImportError:
        return False


def _ocr_languages() -> str:
    """OCR_LANGS limited to what is installed (missing Arabic data degrades to
    English only instead of failing every read)."""
    global _TESSERACT_LANGS
    wanted = [lang for lang in OCR_LANGS.split("+") if lang]
    try:
        import pytesseract
        if _TESSERACT_LANGS is None:
            _TESSERACT_LANGS = pytesseract.get_languages(config="")
        present = [lang for lang in wanted if lang in _TESSERACT_LANGS]
    except Exception:  # noqa: BLE001
        return "eng"
    return "+".join(present) or "eng"


_AMOUNT_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _priced_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if _AMOUNT_RE.search(line))


_CURRENCY_RE = re.compile(r"(?<![A-Za-z])(?:JD|JOD|SAR|SR|AED|USD|EGP|EGP|KWD|QAR|BHD|OMR|LBP|NIS|ILS)(?![A-Za-z])|[$€£]|"
                          r"دينار|ريال|درهم|جنيه|ليرة|شيكل|رانيد|لاير|مهرد", re.IGNORECASE)


def _has_currency(line: str) -> bool:
    return bool(_CURRENCY_RE.search(line))


def merge_passes(texts: List[str]) -> str:
    """One text from several OCR passes over the same picture: the pass with the most lines that carry an
    amount wins, and a line from another pass is added when its amount is missing from the winner. This is
    what recovers "Mansaf 8.50 JD" when the Arabic+English pass reads "JD" as Arabic letters, and an Arabic
    menu when the English-only pass finds nothing."""
    texts = [t for t in texts if t and t.strip()]
    if not texts:
        return ""
    texts.sort(key=_priced_count, reverse=True)  # stable: the first (widest-language) pass wins ties
    merged = texts[0].splitlines()
    seen = {m for line in merged for m in _AMOUNT_RE.findall(line)}
    for other in texts[1:]:
        for line in other.splitlines():
            amounts = _AMOUNT_RE.findall(line)
            if not amounts:
                continue
            if not any(a in seen for a in amounts):
                merged.append(line)
                seen.update(amounts)
            elif _has_currency(line):
                # Same amount already there: prefer this pass's line when the winner's line lost its currency.
                for index, kept in enumerate(merged):
                    if not _has_currency(kept) and any(a in _AMOUNT_RE.findall(kept) for a in amounts):
                        merged[index] = line
                        break
    return "\n".join(merged)


def tesseract_ocr(image) -> str:
    """OCR one PIL image with tesseract; '' when the engine fails. With Arabic data installed it makes two passes
    (Arabic+English, then English only) and merges them - a single mixed-language pass misreads Latin currency
    codes next to Arabic text."""
    import pytesseract
    langs = _ocr_languages()
    passes = [langs] + (["eng"] if "+" in langs and "eng" in langs.split("+") else [])
    texts = []
    for lang in passes:
        try:
            texts.append(pytesseract.image_to_string(image, lang=lang, config="--psm 6", timeout=45))
        except Exception:  # noqa: BLE001 - a bad picture never stops a scan
            logger.warning("OCR pass %s failed for one image", lang, exc_info=True)
    return merge_passes(texts)


def _prepare(image):
    """Greyscale, normalise contrast and upscale small pictures for OCR."""
    from PIL import ImageOps
    image = ImageOps.exif_transpose(image).convert("L")
    image = ImageOps.autocontrast(image)
    if image.width < MIN_OCR_WIDTH:
        factor = MIN_OCR_WIDTH / image.width
        image = image.resize((MIN_OCR_WIDTH, max(1, int(image.height * factor))))
    return image


_BIDI_MARKS = re.compile("[\u200e\u200f\u202a-\u202e\u2066-\u2069]")
_ARABIC = re.compile("[\u0600-\u06ff]")
# Currency words, as written (logical order). Tesseract can return Arabic in visual order (every Arabic word
# reversed, word order reversed); seeing these words reversed is how the order is recognised.
_AR_CURRENCY_WORDS = ("دينار", "ريال", "درهم", "جنيه", "ليرة", "شيكل")


def fix_visual_order(lines: List[str]) -> List[str]:
    """Puts Arabic lines back in logical order when the OCR returned them in visual order. Decided per text, from
    the currency words: more reversed forms ("رانيد") than logical ones ("دينار") means flip every line that has
    Arabic letters. No currency word -> unchanged (prices still parse from their digits)."""
    joined = " ".join(lines)
    logical = sum(joined.count(w) for w in _AR_CURRENCY_WORDS)
    reversed_ = sum(joined.count(w[::-1]) for w in _AR_CURRENCY_WORDS)
    if reversed_ <= logical:
        return lines
    try:
        from bidi.algorithm import get_display
    except ImportError:
        return lines
    return [get_display(line) if _ARABIC.search(line) else line for line in lines]


def fix_currency_words(line: str) -> str:
    """A currency word next to an amount that OCR misread by a letter ("ديذار" for "دينار") is restored; only a
    token touching a number is considered, and only against the known currency words."""
    tokens = line.split(" ")
    for index, token in enumerate(tokens):
        if not (3 <= len(token) <= 6) or not re.fullmatch("[\u0621-\u064a]+", token) or token in _AR_CURRENCY_WORDS:
            continue
        beside = [tokens[i] for i in (index - 1, index + 1) if 0 <= i < len(tokens)]
        if not any(re.fullmatch(r"\d+(?:[.,]\d+)?", t) for t in beside):
            continue
        best = max(_AR_CURRENCY_WORDS, key=lambda w: SequenceMatcher(None, token, w).ratio())
        if SequenceMatcher(None, token, best).ratio() >= 0.78:
            tokens[index] = best
    return " ".join(tokens)


def clean_ocr_lines(text: str) -> List[str]:
    """Lines from OCR text: direction marks removed, Arabic visual order repaired, a few stray Arabic letters
    next to Latin text dropped (a misread "JD"), and letter/digit confusions repaired only inside tokens that
    are otherwise a decimal number ("1O.5O" -> "10.50")."""
    cleaned = []
    for raw in _BIDI_MARKS.sub("", text).splitlines():
        line = re.sub(r"\s+", " ", raw).strip(" \t|_~`")
        if 1 <= len(line) <= 220:
            cleaned.append(line)
    lines = []
    for line in fix_visual_order(cleaned):
        if len(_ARABIC.findall(line)) <= 4 and len(re.findall(r"[A-Za-z]", line)) >= 6:
            line = re.sub(r"\s+", " ", _ARABIC.sub("", line)).strip()
        line = _NUMBERISH.sub(lambda m: m.group(0).translate(_OCR_DIGIT), line)
        lines.append(fix_currency_words(line) if _ARABIC.search(line) else line)
    return lines


def _priced_lines(lines: List[str]) -> int:
    return sum(1 for line in lines if re.search(r"\d", line))


def read_media(data: bytes, content_type: str = "", ocr: Optional[Callable] = None,
               ocr_ready: Optional[bool] = None, vision: Optional[Callable] = None) -> Tuple[List[str], str]:
    """(lines, method) for one downloaded file; method is 'pdf_text', 'ocr',
    'vision', 'skipped_no_ocr', 'unreadable' or 'not_media'. `ocr` takes a PIL
    image and returns text (tests inject one); default is tesseract when
    installed. `vision` (see vision_engine) takes a PIL image and returns text;
    with DISCOVERY_VISION_OCR=fallback it is tried when OCR is missing or got
    fewer than 3 priced lines, with =always it replaces OCR for pictures."""
    kind = sniff(data, content_type)
    if kind is None:
        return [], "not_media"
    ready = ocr_available() if ocr_ready is None else ocr_ready
    engine = ocr or (tesseract_ocr if ready else None)
    try:
        if kind == "pdf":
            return _read_pdf(data, engine, vision)
        if engine is None and vision is None:
            return [], "skipped_no_ocr"
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS:
                return [], "unreadable"
            image.load()
            lines, method = [], "ocr"
            if engine is not None and not (vision is not None and VISION_MODE == "always"):
                lines = clean_ocr_lines(engine(_prepare(image)))
            if vision is not None and (VISION_MODE == "always" or _priced_lines(lines) < 3):
                seen = vision(image)
                if seen and _priced_lines(clean_text_lines(seen)) >= _priced_lines(lines):
                    lines, method = clean_ocr_lines(seen), "vision"
        return lines, (method if lines or method == "vision" else "ocr")
    except Exception:  # noqa: BLE001
        logger.warning("reading a menu file failed", exc_info=True)
        return [], "unreadable"


def vision_engine(limit: Optional[int] = None) -> Optional[Callable]:
    """A callable PIL image -> text that asks a vision model (Gemini, or Groq -
    DISCOVERY_VISION_PROVIDER) to transcribe a menu picture, or None when
    VISION_MODE is off or no key is set. At most `limit` calls (default
    VISION_MAX_FILES) per engine, so one site can only spend a bounded amount;
    each call is a metered paid request (refused, never sent, when the budget
    or the provider price do not allow it - the call then simply returns ''
    and OCR's result stands)."""
    if VISION_MODE not in ("fallback", "always"):
        return None
    gemini_keys = [k.strip() for k in os.getenv("GEMINI_API_KEYS", "").split(",") if k.strip()]
    groq_key = secret("GROQ_API_KEY")
    if VISION_PROVIDER == "groq" or (VISION_PROVIDER == "auto" and not gemini_keys):
        ask = (lambda image: _ask_groq(image, groq_key)) if groq_key else None
    else:
        ask = (lambda image: _ask_gemini(image, gemini_keys[0])) if gemini_keys else None
    if ask is None:
        return None
    left = [VISION_MAX_FILES if limit is None else limit]

    def read(image) -> str:
        if left[0] <= 0:
            return ""
        left[0] -= 1
        return ask(image)
    return read


def _jpeg(image) -> bytes:
    rgb = image.convert("RGB")
    if max(rgb.size) > VISION_MAX_SIDE:
        scale = VISION_MAX_SIDE / max(rgb.size)
        rgb = rgb.resize((max(1, int(rgb.width * scale)), max(1, int(rgb.height * scale))))
    buffer = io.BytesIO()
    rgb.save(buffer, "JPEG", quality=85)
    return buffer.getvalue()


def _ask_groq(image, key: str) -> str:
    """The same transcription through Groq's OpenAI-compatible chat API with a vision model."""
    import httpx

    from src.market_scraper.provider_billing import metered_request

    data_url = "data:image/jpeg;base64," + base64.b64encode(_jpeg(image)).decode()
    body = {"model": GROQ_VISION_MODEL, "temperature": 0, "max_completion_tokens": 2048,
            "messages": [{"role": "user", "content": [{"type": "text", "text": VISION_PROMPT},
                                                      {"type": "image_url", "image_url": {"url": data_url}}]}]}

    def send():
        response = httpx.post(GROQ_VISION_URL, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=60)
        response.raise_for_status()
        return response.json()

    try:
        data = metered_request(GROQ_VISION_URL, send, json_body=None)
        return data["choices"][0]["message"]["content"] or ""
    except Exception as exc:  # noqa: BLE001 - refused budget, HTTP error or odd answer: OCR's result stands
        logger.warning("vision reading of a menu picture failed: %s", type(exc).__name__)
        return ""


def _ask_gemini(image, key: str) -> str:
    import httpx

    from src.market_scraper.provider_billing import metered_request

    body = {"contents": [{"parts": [{"text": VISION_PROMPT},
                                    {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(_jpeg(image)).decode()}}]}],
            "generationConfig": {"temperature": 0}}
    url = VISION_URL.format(model=VISION_MODEL)

    def send():
        response = httpx.post(url, headers={"x-goog-api-key": key}, json=body, timeout=60)  # key in a header, never the URL
        response.raise_for_status()
        return response.json()

    try:
        data = metered_request(url, send, json_body=None)
        parts = data["candidates"][0]["content"]["parts"]
        return "\n".join(p.get("text", "") for p in parts)
    except Exception as exc:  # noqa: BLE001 - refused budget, HTTP error or odd answer: OCR's result stands
        logger.warning("vision reading of a menu picture failed: %s", type(exc).__name__)
        return ""


def _read_pdf(data: bytes, engine: Optional[Callable], vision: Optional[Callable] = None) -> Tuple[List[str], str]:
    import pdfplumber
    lines: List[str] = []
    ocr_pages = vision_pages = 0
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages[:MAX_PDF_PAGES]:
            text = page.extract_text() or ""
            if len(text.strip()) >= 20:
                lines.extend(clean_text_lines(text))
            elif engine is not None or vision is not None:  # scanned page: no text layer
                original = page.to_image(resolution=200).original
                page_lines = clean_ocr_lines(engine(_prepare(original))) if engine is not None and VISION_MODE != "always" else []
                if vision is not None and (VISION_MODE == "always" or _priced_lines(page_lines) < 3):
                    seen = clean_ocr_lines(vision(original) or "")
                    if _priced_lines(seen) >= _priced_lines(page_lines):
                        page_lines, vision_pages = seen, vision_pages + 1
                lines.extend(page_lines)
                ocr_pages += 1
    if not lines and engine is None and vision is None:
        return [], "skipped_no_ocr"
    return lines, ("vision" if vision_pages else "ocr") if ocr_pages else "pdf_text"


def clean_text_lines(text: str) -> List[str]:
    return [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if 1 <= len(line.strip()) <= 220]


# --- facts -------------------------------------------------------------------

def _key(name: str) -> str:
    return re.sub(r"[^\w؀-ۿ]+", " ", (name or "").lower()).strip()


def media_facts(lines: List[str], method: str, source_url: str, retrieved_at: str, country: Optional[str],
                text_prices: Callable[..., List[dict]], max_items: int = 250) -> List[dict]:
    """Price facts from a menu file's lines, through the page reader's own
    price parser (a menu file is a menu page by definition)."""
    items = text_prices(lines, country, True)
    base = {"pdf_text": CONFIDENCE_PDF_TEXT, "vision": CONFIDENCE_VISION}.get(method, CONFIDENCE_OCR)
    facts = []
    for item in items[:max_items]:
        confidence = (CONFIDENCE_OCR_NO_CURRENCY if method == "ocr" else base - 0.1) if item.get("currency_inferred") else base
        facts.append({"kind": "product", "source_url": source_url, "retrieved_at": retrieved_at, "confidence": confidence,
                      "type": "product", "extracted_by": method, "source_media": True, **item})
    return facts


def corroborate(media: List[dict], page_facts: List[dict]) -> List[dict]:
    """Merges media facts into the page facts. A media price that matches a
    page fact (same name, price within 1 %) raises that fact's confidence and
    records the file as a second source instead of adding a duplicate; the
    rest are kept as new, lower-confidence facts. Returns the combined list."""
    index: Dict[str, dict] = {}
    for fact in page_facts:
        if fact.get("kind") == "product" and fact.get("price") is not None:
            index.setdefault(_key(fact.get("name", "")), fact)
    extra = []
    for fact in media:
        match = index.get(_key(fact.get("name", "")))
        price, other = fact.get("price"), match.get("price") if match else None
        if match and price and other and abs(price - other) <= 0.01 * max(price, other):
            sources = match.setdefault("also_seen_in", [])
            if fact["source_url"] not in sources:
                sources.append(fact["source_url"])
                match["confidence"] = round(min(0.98, (match.get("confidence") or 0) + CONFIDENCE_CORROBORATED_BONUS), 3)
        else:
            if match and price and other:  # same item, different price: keep both, flag the disagreement
                fact["conflicts_with_price"] = other
            extra.append(fact)
    return page_facts + extra
