"""
KEEL - Marketing typography layer: campaign text drawn ON an image by KEEL,
not by the image model.

Why: image models that "understand" an Arabic prompt still cannot spell
Arabic - they draw disconnected, mirrored or invented letter shapes. The
campaign's image prompt therefore asks for NO text (content_generator.py's
image_prompt rule), and this module composes the campaign's own headline
and call to action over the finished background as a separate layer:

- shaping: Pillow's libraqm layout (HarfBuzz + FriBiDi - the same shaping a
  browser uses, including diacritic placement) with direction="rtl" for
  Arabic; where Pillow was built without libraqm, arabic-reshaper +
  python-bidi with the BASIC layout instead (designed_poster.py's method);
- wrapping in LOGICAL order, one shaped line at a time (wrapping an already
  reordered string reverses the line order);
- right-aligned Arabic, left-aligned Latin, on a soft scrim so the text stays
  legible on any background; the CTA in a pill.

Only text the campaign already has is drawn (pick_copy); nothing invented.
Pure Pillow, no network. compose() returns PNG bytes.
"""
import io
import os
import re
from typing import Optional, Tuple, Union

from PIL import Image, ImageDraw, ImageFont, features

_ARABIC = re.compile("[\u0600-\u06ffݐ-ݿ\ufb50-\ufdff\ufe70-\ufeff]")
_FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports_pdf_fonts")
_FONTS = (
    os.getenv("MARKETING_FONT_PATH", ""),
    "/usr/share/fonts/truetype/noto/NotoKufiArabic-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Bold.ttf",
    os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)
RAQM = features.check("raqm")


def is_rtl(text: str) -> bool:
    letters = [ch for ch in text or "" if ch.isalpha()]
    arabic = sum(1 for ch in letters if _ARABIC.match(ch))
    return arabic > 0 and arabic >= len(letters) - arabic


_COVERAGE: dict = {}


def _glyph_pixels(font, ch: str) -> bytes:
    canvas = Image.new("L", (64, 64))
    ImageDraw.Draw(canvas).text((8, 8), ch, font=font, fill=255)
    return canvas.tobytes()


def _has_glyph(path: str, ch: str) -> bool:
    """False when the font would draw its .notdef box for `ch` (compared with a
    code point no font defines)."""
    key = (path, ch)
    if key not in _COVERAGE:
        font = ImageFont.truetype(path, 40, layout_engine=ImageFont.Layout.BASIC)
        _COVERAGE[key] = ch.isspace() or _glyph_pixels(font, ch) != _glyph_pixels(font, "\U0010FFFD")
    return _COVERAGE[key]


def _font_path(text: str = "") -> Optional[str]:
    """The first available font that has a glyph for every character of
    `text` (Noto Kufi Arabic has no en dash, for instance), else the first
    available font."""
    available = [path for path in _FONTS if path and os.path.isfile(path)]
    for path in available:
        if all(_has_glyph(path, ch) for ch in set(text)):
            return path
    return available[0] if available else None


def _font(size: int, text: str = ""):
    path = _font_path(text)
    if path is None:
        return ImageFont.load_default(size)
    engine = ImageFont.Layout.RAQM if RAQM else ImageFont.Layout.BASIC
    return ImageFont.truetype(path, size, layout_engine=engine)


def _shaped(text: str, rtl: bool) -> Tuple[str, dict]:
    """(string to draw, draw kwargs). With libraqm the logical string is
    passed with its direction; without it, it is reshaped and reordered."""
    if not rtl:
        return text, {"direction": "ltr"} if RAQM else {}
    if RAQM:
        return text, {"direction": "rtl", "language": "ar"}
    import arabic_reshaper
    from bidi.algorithm import get_display

    return get_display(arabic_reshaper.reshape(text), base_dir="R"), {}


def _width(draw, text: str, font, rtl: bool) -> float:
    shaped, kwargs = _shaped(text, rtl)
    return draw.textlength(shaped, font=font, **kwargs)


def wrap(draw, text: str, font, max_width: float, rtl: bool):
    """Lines of `text` in logical order, each at most max_width when drawn."""
    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if current and _width(draw, trial, font, rtl) > max_width:
            lines.append(current)
            current = word
        else:
            current = trial
    return lines + ([current] if current else [])


def _fit(draw, text: str, start: int, max_width: float, max_lines: int, rtl: bool):
    size = start
    while size > 20:
        font = _font(size, text)
        lines = wrap(draw, text, font, max_width, rtl)
        if len(lines) <= max_lines and all(_width(draw, l, font, rtl) <= max_width for l in lines):
            return font, lines
        size -= 4
    font = _font(20, text)
    return font, wrap(draw, text, font, max_width, rtl)[:max_lines]


def compose(background: Union[bytes, Image.Image], headline: str, cta: Optional[str] = None,
            language: Optional[str] = None, accent: Tuple[int, int, int] = (20, 20, 20),
            text_color: Tuple[int, int, int] = (255, 255, 255)) -> bytes:
    """PNG bytes: `background` with the headline (and CTA) laid over its lower
    part. `language` "ar" forces right-to-left; otherwise detected from the text."""
    image = background if isinstance(background, Image.Image) else Image.open(io.BytesIO(background))
    image = image.convert("RGBA")
    width, height = image.size
    unit = min(width, height)
    margin = int(unit * 0.07)
    headline = (headline or "").strip()
    cta = (cta or "").strip() or None
    rtl = language == "ar" or (language is None and is_rtl(headline))

    measure = ImageDraw.Draw(image)
    head_font, lines = _fit(measure, headline, int(unit * 0.085), width - 2 * margin, 3, rtl)
    line_height = int(head_font.size * 1.3)
    cta_font = _font(int(unit * 0.042), cta or "")
    cta_h = int(cta_font.size * 2.0) if cta else 0
    block_h = len(lines) * line_height + (cta_h + int(unit * 0.03) if cta else 0)

    # Scrim: a dark gradient behind the text block for legibility on any photo.
    top = max(0, height - margin - block_h - int(unit * 0.08))
    scrim = Image.new("L", (1, height - top))
    for y in range(height - top):
        scrim.putpixel((0, y), int(185 * min(1.0, y / max(1, (height - top) * 0.45))))
    shade = Image.new("RGBA", (width, height - top), (0, 0, 0, 255))
    shade.putalpha(scrim.resize((width, height - top)))
    image.alpha_composite(shade, (0, top))

    draw = ImageDraw.Draw(image)
    y = height - margin - block_h
    for line in lines:
        shaped, kwargs = _shaped(line, rtl)
        x, anchor = (width - margin, "ra") if rtl else (margin, "la")
        draw.text((x + 2, y + 2), shaped, font=head_font, fill=(0, 0, 0, 160), anchor=anchor, **kwargs)
        draw.text((x, y), shaped, font=head_font, fill=text_color, anchor=anchor, **kwargs)
        y += line_height
    if cta:
        y += int(unit * 0.03)
        cta_rtl = rtl if is_rtl(cta) or rtl else False
        shaped, kwargs = _shaped(cta, cta_rtl)
        pill_w = int(draw.textlength(shaped, font=cta_font, **kwargs)) + int(unit * 0.09)
        x0 = width - margin - pill_w if rtl else margin
        draw.rounded_rectangle((x0, y, x0 + pill_w, y + cta_h), radius=cta_h // 2, fill=(255, 255, 255, 235))
        draw.text((x0 + pill_w / 2, y + cta_h / 2), shaped, font=cta_font, fill=accent, anchor="mm", **kwargs)

    out = io.BytesIO()
    image.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()


def render_line(text: str, size: int = 72, rtl: Optional[bool] = None) -> Image.Image:
    """One line drawn black on white through exactly the shaping path compose()
    uses - for verification (OCR) and previews."""
    rtl = is_rtl(text) if rtl is None else rtl
    font = _font(size, text)
    shaped, kwargs = _shaped(text, rtl)
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    width = int(probe.textlength(shaped, font=font, **kwargs)) + 2 * size
    canvas = Image.new("L", (width, int(size * 2.2)), 255)
    ImageDraw.Draw(canvas).text((width / 2, size * 1.1), shaped, font=font, fill=0, anchor="mm", **kwargs)
    return canvas
