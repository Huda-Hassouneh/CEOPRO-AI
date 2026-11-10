"""
KEEL - Automated Marketing: art-directed advertisement composer (local, free).

Builds a finished social-media advertisement on our own server with Pillow +
numpy only (no network, no key, no per-image cost): a lit scene, the owner's
REAL product as the hero, and the campaign's own copy laid out around it.
It replaces the old flat "gradient + headline" designed poster.

What adapts, and from what (nothing is product-specific or hard-coded):

* Look (light, surface, atmosphere, typography) - from the campaign's
  creative_theme; when there is none, from its strategy_type (objective).
* Colours - from the product photo itself (its dominant and most saturated
  colours), so every scene is tinted to the product it sells.
* Layout - from the image format (square / portrait / story / landscape /
  wide), the product's own shape (a wide product gets a stacked layout) and
  the copy's direction (Arabic mirrors the layout right-to-left).
* Emphasis - from the objective: a sales / urgency campaign gets a bold
  call-to-action, brand awareness a quiet one, storytelling its supporting
  line.

Honesty rules (kept from designed_poster.py):

* The product is the photo's own pixels (cut out by product_composite) -
  only light, shadow and reflection are added around it, never a new label,
  shape, size or feature.
* The only words drawn are the campaign's own generated headline, the first
  sentence of that same variant's body copy, and its CTA. Nothing invented.
* No photo / an uncuttable photo: no product is drawn (or the photo is shown
  as a framed print) - a product is never imagined.
"""
from __future__ import annotations

import colorsys
import io
import math
import os
import random
import re
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

try:  # Arabic shaping; both are in requirements.txt
    import arabic_reshaper
    from bidi.algorithm import get_display
except ImportError:  # pragma: no cover
    arabic_reshaper = get_display = None

RGB = Tuple[int, int, int]
_FONT_DIR = Path(__file__).resolve().parent / "fonts"
_ARABIC = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")


# --------------------------------------------------------------------------- looks
@dataclass(frozen=True)
class Look:
    name: str
    mood: str            # dark | warm | light | vivid | pastel
    surface: str         # stone | wood | studio | podium
    serif: bool          # elegant display serif vs. strong sans headline
    rays: bool
    bokeh: int           # number of out-of-focus highlights
    atmosphere: str      # soft | foliage | streaks | shapes | none
    light: RGB           # colour of the key light
    glossy: bool         # floor shows a reflection of the product


LOOKS = {
    "luxury": Look("luxury", "dark", "stone", True, True, 26, "soft", (255, 214, 150), True),
    "natural": Look("natural", "warm", "wood", True, True, 40, "foliage", (255, 214, 140), False),
    "minimal": Look("minimal", "light", "studio", True, False, 0, "soft", (255, 250, 242), True),
    "tech": Look("tech", "dark", "studio", False, False, 18, "streaks", (170, 205, 255), True),
    "bold": Look("bold", "vivid", "podium", False, True, 14, "shapes", (255, 244, 220), False),
    "playful": Look("playful", "pastel", "podium", False, False, 22, "shapes", (255, 248, 240), False),
}

THEME_TO_LOOK = {
    "LUXURY_PREMIUM": "luxury", "MINIMAL_CLEAN": "minimal", "MODERN_TECH": "tech",
    "SOCIAL_TRENDY": "playful", "BOLD_PROMOTIONAL": "bold", "LIFESTYLE": "natural", "SEASONAL": "playful",
}
# Campaign objective -> look, used only when no named theme was chosen (None / CUSTOM).
OBJECTIVE_TO_LOOK = {
    "SALES_DRIVEN": "minimal", "BRAND_AWARENESS": "luxury", "STORYTELLING": "natural",
    "URGENCY": "bold", "INFLUENCER_STYLE": "playful",
}


def choose_look(campaign: dict) -> Look:
    name = THEME_TO_LOOK.get(campaign.get("creative_theme") or "")
    if name is None:
        name = OBJECTIVE_TO_LOOK.get(campaign.get("strategy_type") or "", "minimal")
    return LOOKS[name]


# --------------------------------------------------------------------------- copy
def _clean(text: str) -> str:
    text = re.sub(r"https?://\S+|#\S+|@\S+", "", text or "")
    text = re.sub(r"[\U0001F000-\U0001FAFF☀-➿️]", "", text)  # emoji
    return " ".join(text.split())


def pick_copy(campaign: dict) -> Tuple[str, Optional[str], Optional[str]]:
    """(headline, supporting line, cta) - all from the campaign's own generated
    content (one variant, Instagram first), else the brief's first line.
    The supporting line is the first sentence of that variant's body copy,
    used only when it is short enough to read on an image. Nothing invented."""
    content = campaign.get("content") or {}
    for platform in ("INSTAGRAM", "FACEBOOK", *content):
        for variant in content.get(platform) or []:
            headline = _clean(variant.get("headline") or "")
            if not headline:
                continue
            cta = _clean(variant.get("cta") or "")[:30] or None
            body = _clean(variant.get("body_copy") or "")
            first = re.split(r"(?<=[.!?؟۔])\s", body, maxsplit=1)[0] if body else ""
            support = first if 12 <= len(first) <= 110 and first.lower() != headline.lower() else None
            return headline[:70], support, cta
    brief = (campaign.get("campaign_brief") or "").strip().splitlines()
    return (_clean(brief[0])[:70] if brief and brief[0].strip() else "New"), None, None


def is_rtl(*texts: Optional[str]) -> bool:
    return any(t and _ARABIC.search(t) for t in texts)


def _shape(text: str) -> str:
    if text and _ARABIC.search(text) and arabic_reshaper and get_display:
        return get_display(arabic_reshaper.reshape(text), base_dir="R")
    return text


# --------------------------------------------------------------------------- fonts
_ARABIC_FONTS = (
    os.getenv("MARKETING_FONT_PATH", ""),
    str(Path(__file__).resolve().parent.parent / "reports_pdf_fonts" / "DejaVuSans-Bold.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)
_LATIN = {
    "display": "PlayfairDisplay_400Regular.ttf", "display_italic": "PlayfairDisplay_400Regular_Italic.ttf",
    "display_bold": "PlayfairDisplay_700Bold.ttf", "sans": "Inter_400Regular.ttf",
    "sans_semibold": "Inter_600SemiBold.ttf", "sans_black": "Inter_800ExtraBold.ttf",
}


def font(kind: str, size: int, arabic: bool = False):
    # BASIC layout: _shape() already reorders RTL text (a Raqm Pillow would reverse it twice).
    paths = list(_ARABIC_FONTS) if arabic else [str(_FONT_DIR / _LATIN.get(kind, _LATIN["sans"])), *_ARABIC_FONTS]
    for path in paths:
        if path and os.path.isfile(path):
            try:
                return ImageFont.truetype(path, max(8, int(size)), layout_engine=ImageFont.Layout.BASIC)
            except OSError:
                continue
    return ImageFont.load_default(max(8, int(size)))


# --------------------------------------------------------------------------- colour
def _hsv(rgb: RGB) -> Tuple[float, float, float]:
    return colorsys.rgb_to_hsv(*(c / 255 for c in rgb))


def _rgb(h: float, s: float, v: float) -> RGB:
    return tuple(int(round(c * 255)) for c in colorsys.hsv_to_rgb(h % 1.0, max(0, min(1, s)), max(0, min(1, v))))


def _mix(a: RGB, b: RGB, t: float) -> RGB:
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _lum(rgb) -> float:
    r, g, b = (c / 255 for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


@dataclass(frozen=True)
class Palette:
    hue: float
    sat: float
    product: RGB          # dominant product colour
    edge: RGB             # backdrop at the frame edge
    mid: RGB              # backdrop around the light
    core: RGB             # the light itself
    accent: RGB           # CTA / highlighted line
    on_accent: RGB
    text: RGB
    shade: RGB            # colour of soft background shapes


def product_colours(product: Optional[Image.Image]) -> Tuple[RGB, RGB, float]:
    """(dominant colour, most saturated colour, its saturation) of the product's
    opaque pixels. Neutral grey when there is no product."""
    if product is None:
        return (128, 128, 128), (128, 128, 128), 0.0
    small = product.convert("RGBA").copy()
    small.thumbnail((96, 96))
    arr = np.asarray(small).reshape(-1, 4)
    arr = arr[arr[:, 3] > 200][:, :3]
    if len(arr) < 20:
        return (128, 128, 128), (128, 128, 128), 0.0
    img = Image.fromarray(arr.reshape(1, -1, 3).astype(np.uint8), "RGB").quantize(colors=6, kmeans=2)
    pal = img.getpalette()[:18]
    counts = sorted(img.getcolors(), reverse=True)
    colours = [(n, tuple(pal[i * 3:i * 3 + 3])) for n, i in counts]
    dominant = colours[0][1]

    def vivid(item):
        n, c = item
        h, s, v = _hsv(c)
        return n * (s ** 1.5) * min(1.0, v * 1.6)

    n, saturated = max(colours, key=vivid)
    s = _hsv(saturated)[1] if n >= len(arr) * 0.04 else 0.0
    return dominant, saturated, s


_FALLBACK_HUE = {"luxury": 0.10, "natural": 0.09, "minimal": 0.08, "tech": 0.58, "bold": 0.04, "playful": 0.92}


def make_palette(look: Look, product: Optional[Image.Image]) -> Palette:
    dominant, saturated, sat = product_colours(product)
    colourful = sat >= 0.22
    hue = _hsv(saturated)[0] if colourful else _FALLBACK_HUE[look.name]
    s = min(sat, 0.85) if colourful else 0.35
    if look.mood == "warm":  # golden hour: always warm, nudged toward the product's own hue
        edge, mid, core = (20, 12, 5), (139, 86, 27), (255, 222, 150)
        if colourful:
            mid = _mix(mid, _rgb(hue, 0.7, 0.55), 0.25)
        accent, on_accent, text, shade = (238, 189, 85), (42, 26, 6), (251, 243, 226), (38, 44, 16)
    elif look.mood == "dark":
        edge = _rgb(hue, min(s, 0.55), 0.06)
        mid = _rgb(hue, min(s, 0.65), 0.30)
        core = _mix(look.light, (255, 255, 255), 0.45)
        if look.name == "tech":
            accent = _rgb(hue if colourful else 0.55, 0.55, 1.0)
            on_accent = (8, 12, 22)
        else:
            accent, on_accent = (233, 192, 108), (28, 20, 8)
        text, shade = (247, 241, 230), _rgb(hue, min(s, 0.5), 0.12)
    elif look.mood == "vivid":  # complementary backdrop so the product pops
        bh = (hue + 0.5) % 1.0 if colourful else hue
        edge, mid, core = _rgb(bh, 0.92, 0.42), _rgb(bh, 0.88, 0.86), _rgb(bh, 0.30, 1.0)
        accent, on_accent, text, shade = (18, 16, 20), (255, 255, 255), (255, 255, 255), _rgb(bh, 0.9, 0.62)
    elif look.mood == "pastel":
        bh = (hue + 0.5) % 1.0 if colourful else hue
        edge, mid, core = _rgb(bh, 0.30, 0.90), _rgb(bh, 0.16, 0.98), (255, 255, 255)
        accent = _rgb(hue, max(0.65, s), 0.78)
        on_accent, text, shade = (255, 255, 255), _rgb(hue, 0.45, 0.18), _rgb(hue, 0.35, 0.95)
    else:  # light / minimal studio
        edge, mid, core = _rgb(hue, s * 0.22, 0.84), _rgb(hue, s * 0.10, 0.95), (255, 255, 255)
        accent = _rgb(hue, max(0.55, s), 0.42) if colourful else (28, 30, 36)
        on_accent, text, shade = (255, 255, 255), _rgb(hue, 0.25, 0.13), _rgb(hue, s * 0.3, 0.80)
    return Palette(hue, s, dominant, edge, mid, core, accent, on_accent, text, shade)


# --------------------------------------------------------------------------- numpy helpers
def _f(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0


def _img(arr: np.ndarray) -> Image.Image:
    return Image.fromarray((np.clip(arr, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")


def _screen(base: np.ndarray, layer: Image.Image) -> np.ndarray:
    """Screen-blends an RGBA layer (light) onto base."""
    a = np.asarray(layer, dtype=np.float32) / 255.0
    add = a[..., :3] * a[..., 3:4]
    return 1 - (1 - base) * (1 - add)


def _over(base: np.ndarray, layer: Image.Image) -> np.ndarray:
    a = np.asarray(layer, dtype=np.float32) / 255.0
    return base * (1 - a[..., 3:4]) + a[..., :3] * a[..., 3:4]


def _radial(w: int, h: int, cx: float, cy: float, r: float) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    return np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / max(1.0, r)


def _ramp(d: np.ndarray, stops) -> np.ndarray:
    """Colour ramp over distance d (0..1+) with [(pos, rgb), ...] stops."""
    pos = np.array([p for p, _ in stops], np.float32)
    out = np.empty(d.shape + (3,), np.float32)
    for c in range(3):
        out[..., c] = np.interp(d, pos, np.array([col[c] / 255 for _, col in stops], np.float32))
    return out


def _noise(w: int, h: int, cells: Tuple[int, int], rng: np.random.Generator) -> np.ndarray:
    """Smooth value noise in 0..1, stretched by `cells` (columns, rows)."""
    small = (rng.random((max(2, cells[1]), max(2, cells[0]))) * 255).astype(np.uint8)
    return np.asarray(Image.fromarray(small, "L").resize((w, h), Image.BICUBIC), np.float32) / 255.0


def _aa_mask(size: Tuple[int, int], draw_fn, ss: int = 4) -> Image.Image:
    """Anti-aliased L mask: draw_fn(draw, ss) at ss x, then downsample."""
    big = Image.new("L", (size[0] * ss, size[1] * ss), 0)
    draw_fn(ImageDraw.Draw(big), ss)
    return big.resize(size, Image.LANCZOS)


def _layer(size, colour: RGB, mask: Image.Image, opacity: float = 1.0) -> Image.Image:
    out = Image.new("RGBA", size, colour + (0,))
    out.putalpha(mask.point(lambda v: int(v * opacity)) if opacity != 1.0 else mask)
    return out


# --------------------------------------------------------------------------- layout
@dataclass
class Layout:
    stacked: bool
    rtl: bool
    text_box: Tuple[int, int, int, int]       # x0, y0, x1, y1
    align: str                                 # left | right | center
    product_cx: int
    product_max: Tuple[int, int]
    baseline: int
    horizon: int
    light: Tuple[int, int]
    cta_bottom: bool


def _format_of(size: Tuple[int, int]) -> str:
    r = size[0] / size[1]
    if r > 1.6:
        return "WIDE"
    if r > 1.2:
        return "LANDSCAPE"
    if r > 0.9:
        return "SQUARE"
    if r > 0.7:
        return "PORTRAIT"
    return "STORY"


def plan_layout(fmt: str, size: Tuple[int, int], product_aspect: Optional[float], rtl: bool) -> Layout:
    w, h = size
    unit = min(w, h)
    m = int(unit * 0.075)
    wide_product = product_aspect is not None and product_aspect > 1.25
    stacked = fmt == "STORY" or product_aspect is None or (fmt in ("SQUARE", "PORTRAIT") and wide_product)
    if stacked:
        top = {"STORY": 0.40, "PORTRAIT": 0.40, "SQUARE": 0.40}.get(fmt, 0.42)
        baseline = int(h * {"STORY": 0.79, "PORTRAIT": 0.86, "SQUARE": 0.88}.get(fmt, 0.88))
        text_box = (m, int(h * 0.09) if fmt == "STORY" else int(m * 1.2), w - m, int(h * top))
        product_max = (int(w * 0.80), max(40, baseline - int(h * top) - int(unit * 0.04)))
        cx = w // 2
        light = (int(w * 0.5), int(h * top))
        if product_aspect is None:  # no product: copy sits in the optical centre
            text_box = (m, int(h * 0.18), w - m, int(h * 0.80))
            light = (int(w * 0.5), int(h * 0.42))
        layout = Layout(True, rtl, text_box, "center", cx, product_max, baseline,
                        baseline - int(unit * 0.10), light, fmt == "STORY" and product_aspect is not None)
    else:
        side = {"LANDSCAPE": 0.44, "WIDE": 0.46}.get(fmt, 0.47)
        baseline = int(h * {"PORTRAIT": 0.87, "SQUARE": 0.88, "LANDSCAPE": 0.88, "WIDE": 0.89}.get(fmt, 0.87))
        text_w = int(w * side)
        cx = int(w * (side + (1 - side) / 2)) + int(unit * 0.01)
        product_max = (int(w * (1 - side) - m * 2.2), int(h * {"LANDSCAPE": 0.72, "WIDE": 0.74}.get(fmt, 0.68)))
        text_box = (m, m, m + text_w - int(m * 0.4), baseline)
        light = (cx + int(unit * 0.16), int(h * 0.20))
        layout = Layout(False, rtl, text_box, "left", cx, product_max, baseline,
                        baseline - int(unit * 0.095), light, False)
        if rtl:  # mirror: copy on the right, product on the left
            x0, y0, x1, y1 = text_box
            layout.text_box = (w - x1, y0, w - x0, y1)
            layout.align = "right"
            layout.product_cx = w - cx
            layout.light = (w - light[0], light[1])
    return layout


# --------------------------------------------------------------------------- scene
def _backdrop(w, h, lay: Layout, pal: Palette, look: Look) -> np.ndarray:
    lx, ly = lay.light
    d = _radial(w, h, lx, ly, math.hypot(w, h) * 0.95)
    if look.mood in ("dark", "warm"):
        stops = [(0, _mix(pal.core, (255, 255, 255), 0.6)), (0.05, pal.core), (0.17, _mix(pal.core, pal.mid, 0.55)),
                 (0.38, pal.mid), (0.66, _mix(pal.mid, pal.edge, 0.7)), (1.0, pal.edge)]
    else:
        stops = [(0, pal.core), (0.22, _mix(pal.core, pal.mid, 0.6)), (0.5, pal.mid), (1.0, pal.edge)]
    return _ramp(d, stops)


def _atmosphere(size, lay: Layout, pal: Palette, look: Look, rng: random.Random) -> Optional[Image.Image]:
    w, h = size
    unit = min(w, h)
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    if look.atmosphere == "foliage":  # out-of-focus grove / greenery
        shades = [_mix(pal.shade, (0, 0, 0), t) for t in (0.0, 0.2, 0.4)] + [(61, 61, 22), (74, 68, 25)]
        for _ in range(11):
            cx, cy, r = rng.uniform(0, w), rng.uniform(h * 0.25, lay.horizon), rng.uniform(unit * 0.12, unit * 0.22)
            for _ in range(70):
                a, dist = rng.uniform(0, math.tau), math.sqrt(rng.random()) * r
                x, y = cx + math.cos(a) * dist, cy + math.sin(a) * dist * 0.7
                lw, lh = rng.uniform(unit * 0.015, unit * 0.028), rng.uniform(unit * 0.004, unit * 0.008)
                leaf = Image.new("RGBA", (int(lw * 2 + 4), int(lw * 2 + 4)), (0, 0, 0, 0))
                ImageDraw.Draw(leaf).ellipse((2, lw - lh + 2, lw * 2 + 2, lw + lh + 2),
                                             fill=rng.choice(shades) + (int(rng.uniform(110, 215)),))
                leaf = leaf.rotate(rng.uniform(-70, 70))
                layer.alpha_composite(leaf, (int(max(0, min(w - 1, x - lw))), int(max(0, min(h - 1, y - lw)))))
        return layer.filter(ImageFilter.GaussianBlur(unit * 0.013))
    if look.atmosphere == "streaks":  # tech: soft diagonal light streaks and a faint grid
        for _ in range(7):
            x = rng.uniform(-w * 0.2, w)
            d.line((x, -10, x + h * 0.6, h + 10), fill=_mix(pal.accent, (255, 255, 255), 0.3) + (int(rng.uniform(25, 60)),),
                   width=max(1, int(unit * rng.uniform(0.002, 0.008))))
        step = int(unit * 0.09)
        for x in range(0, w, step):
            d.line((x, 0, x, lay.horizon), fill=pal.accent + (10,), width=1)
        for y in range(0, lay.horizon, step):
            d.line((0, y, w, y), fill=pal.accent + (10,), width=1)
        return layer.filter(ImageFilter.GaussianBlur(unit * 0.003))
    if look.atmosphere == "shapes":  # big soft colour fields for depth
        for _ in range(6):
            r = rng.uniform(unit * 0.12, unit * 0.30)
            x, y = rng.uniform(0, w), rng.uniform(0, h * 0.8)
            col = _mix(pal.shade, (255, 255, 255), rng.uniform(0, 0.35))
            d.ellipse((x - r, y - r, x + r, y + r), fill=col + (int(rng.uniform(60, 130)),))
        return layer.filter(ImageFilter.GaussianBlur(unit * 0.05))
    if look.atmosphere == "soft":
        for _ in range(5):
            r = rng.uniform(unit * 0.15, unit * 0.32)
            x, y = rng.uniform(0, w), rng.uniform(h * 0.15, lay.horizon)
            d.ellipse((x - r, y - r * 0.6, x + r, y + r * 0.6), fill=pal.shade + (int(rng.uniform(40, 90)),))
        return layer.filter(ImageFilter.GaussianBlur(unit * 0.06))
    return None


def _rays(size, lay: Layout, pal: Palette, rng: random.Random) -> Image.Image:
    w, h = size
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    lx, ly = lay.light
    far = math.hypot(w, h) * 1.4
    toward = math.atan2(h - ly, (w / 2) - lx)  # fan toward the lower frame
    for _ in range(7):
        a = toward + rng.uniform(-0.75, 0.75)
        spread = rng.uniform(0.02, 0.06)
        pts = [(lx, ly), (lx + math.cos(a - spread) * far, ly + math.sin(a - spread) * far),
               (lx + math.cos(a + spread) * far, ly + math.sin(a + spread) * far)]
        d.polygon(pts, fill=pal.core + (int(rng.uniform(22, 48)),))
    return layer.filter(ImageFilter.GaussianBlur(min(w, h) * 0.022))


def _bokeh(size, lay: Layout, pal: Palette, look: Look, rng: random.Random, avoid) -> Image.Image:
    w, h = size
    unit = min(w, h)
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    col = _mix(pal.core, look.light, 0.5)
    lx, ly = lay.light
    placed = 0
    for _ in range(look.bokeh * 4):
        if placed >= look.bokeh:
            break
        near = rng.random() < 0.65
        x = lx + rng.uniform(-unit * 0.35, unit * 0.35) if near else rng.uniform(0, w)
        y = ly + rng.uniform(-unit * 0.25, unit * 0.40) if near else rng.uniform(0, lay.horizon)
        x0, y0, x1, y1 = avoid
        if x0 - unit * 0.02 < x < x1 and y0 < y < y1:  # keep highlights off the copy
            continue
        r = rng.uniform(unit * 0.008, unit * 0.042)
        disc = Image.new("RGBA", (int(r * 2 + 6),) * 2, (0, 0, 0, 0))
        dd = ImageDraw.Draw(disc)
        a = rng.uniform(0.18, 0.55)
        dd.ellipse((3, 3, 3 + 2 * r, 3 + 2 * r), fill=col + (int(255 * a * 0.6),))
        dd.ellipse((3, 3, 3 + 2 * r, 3 + 2 * r), outline=col + (int(255 * a),), width=max(1, int(r * 0.12)))
        disc = disc.filter(ImageFilter.GaussianBlur(max(0.8, r * 0.06)))
        layer.alpha_composite(disc, (int(max(0, min(w - disc.width, x - r))), int(max(0, min(h - disc.height, y - r)))))
        placed += 1
    if look.mood in ("warm", "dark"):  # floating dust in the light
        md = ImageDraw.Draw(layer)
        for _ in range(int(look.bokeh * 0.9)):
            x, y = lx + rng.uniform(-unit * 0.45, unit * 0.35), rng.uniform(h * 0.05, lay.horizon)
            if avoid[0] < x < avoid[2] and avoid[1] < y < avoid[3]:
                continue
            r = rng.uniform(unit * 0.0008, unit * 0.002)
            md.ellipse((x - r, y - r, x + r, y + r), fill=(255, 243, 207, int(rng.uniform(80, 200))))
    return layer


def _surface(arr: np.ndarray, lay: Layout, pal: Palette, look: Look, nrng: np.random.Generator) -> np.ndarray:
    h, w, _ = arr.shape
    unit = min(w, h)
    hz = lay.horizon
    depth = h - hz
    if depth <= 4:
        return arr
    t = np.linspace(0, 1, depth, dtype=np.float32)[:, None, None]  # 0 at the back edge, 1 at the front
    lx = lay.light[0]
    xx = np.linspace(0, w - 1, w, dtype=np.float32)[None, :, None]
    pool = np.exp(-((xx - lx) / (w * 0.45)) ** 2) * (1 - t) ** 1.5  # light falling on the surface
    light = np.array(look.light, np.float32) / 255
    if look.surface == "wood":
        grain = _noise(w, depth, (6, 60), nrng) * 0.55 + _noise(w, depth, (3, 160), nrng) * 0.45
        grain = 0.5 + 0.5 * np.sin(grain * 38.0)
        back, front = np.array([176, 122, 62], np.float32) / 255, np.array([44, 26, 11], np.float32) / 255
        base = back + (front - back) * t ** 0.7
        surf = base * (0.72 + 0.38 * grain[..., None])
        for k, frac in enumerate((0.15, 0.37, 0.68)):  # plank seams, spaced for perspective
            y = int(depth * frac)
            th = max(1, int(unit * 0.002 * (1 + k * 0.4)))
            surf[y:y + th] *= 0.35
            surf[y + th:y + th * 2] = np.minimum(1, surf[y + th:y + th * 2] * 1.25)
    elif look.surface == "stone":
        n = _noise(w, depth, (5, 3), nrng)
        vein_n = _noise(w, depth, (4, 3), nrng)
        veins = np.exp(-((vein_n - 0.5) / 0.012) ** 2) * 0.6 + np.exp(-((vein_n - 0.3) / 0.006) ** 2) * 0.35
        base_c = np.array(_mix(pal.edge, (40, 38, 36), 0.5), np.float32) / 255
        surf = base_c * (0.9 + 0.25 * n[..., None]) * (1.25 - 0.55 * t)
        surf = surf + veins[..., None] * np.array(_mix(look.light, (200, 200, 200), 0.5), np.float32) / 255 * 0.10
    elif look.surface == "podium":
        floor = np.array(_mix(pal.edge, (0, 0, 0), 0.12 if look.mood == "vivid" else 0.04), np.float32) / 255
        surf = np.broadcast_to(floor, (depth, w, 3)) * (1.05 - 0.25 * t)
    else:  # studio sweep: continues the backdrop with a soft floor fall-off
        top = arr[hz - 1:hz].copy()
        surf = top * (1.0 - 0.28 * t ** 0.8)
    surf = surf + pool * light * (0.55 if look.mood in ("warm", "dark") else 0.18)
    if look.surface in ("studio", "podium"):  # seamless: blend the floor into the wall
        blend = np.clip(np.linspace(0, 1, depth, dtype=np.float32) / 0.25, 0, 1)[:, None, None]
        surf = arr[hz:] * (1 - blend) + surf * blend
    out = arr.copy()
    out[hz:] = np.clip(surf, 0, 1)
    if look.surface in ("wood", "stone"):  # rim light on the back edge
        rim = max(1, int(unit * 0.004))
        out[hz:hz + rim] = np.minimum(1, out[hz:hz + rim] * 0.6 + light * 0.55)
    return out


# --------------------------------------------------------------------------- product
def _fit_product(product: Image.Image, box: Tuple[int, int]) -> Image.Image:
    scale = min(box[0] / product.width, box[1] / product.height)
    return product.resize((max(1, int(product.width * scale)), max(1, int(product.height * scale))), Image.LANCZOS)


def framed_photo(photo: Image.Image) -> Image.Image:
    """An uncuttable photo shown honestly as a print with a white border."""
    photo = ImageOps.exif_transpose(photo).convert("RGB")
    photo.thumbnail((1600, 1600), Image.LANCZOS)
    pad = int(min(photo.size) * 0.035)
    card = Image.new("RGBA", (photo.width + 2 * pad, photo.height + 2 * pad), (0, 0, 0, 0))
    radius = pad * 2
    mask = _aa_mask(card.size, lambda d, s: d.rounded_rectangle((0, 0, card.width * s - 1, card.height * s - 1),
                                                                 radius=radius * s, fill=255), ss=2)
    card.paste((252, 250, 246, 255), mask=mask)
    inner = _aa_mask(photo.size, lambda d, s: d.rounded_rectangle((0, 0, photo.width * s - 1, photo.height * s - 1),
                                                                   radius=int(radius * 0.6) * s, fill=255), ss=2)
    card.paste(photo, (pad, pad), inner)
    return card


def _place_product(arr: np.ndarray, item: Image.Image, x: int, y: int, lay: Layout, pal: Palette,
                   look: Look, podium_h: int) -> np.ndarray:
    h, w, _ = arr.shape
    unit = min(w, h)
    size = (w, h)
    alpha = item.getchannel("A")
    side = 1 if lay.light[0] >= x + item.width / 2 else -1  # light comes from this side

    # Backlight halo behind the product.
    hcx, hcy = x + item.width / 2, y + item.height * 0.42
    hr = max(item.width, item.height) * 0.75
    falloff = np.clip(1 - _radial(w, h, hcx, hcy, hr), 0, 1) ** 2.2
    halo = Image.fromarray((falloff * 255).astype(np.uint8), "L")
    strength = {"dark": 0.55, "warm": 0.45, "vivid": 0.45, "pastel": 0.7, "light": 0.8}[look.mood]
    arr = _screen(arr, _layer(size, _mix(pal.core, look.light, 0.4), halo, strength))

    base_y = y + item.height
    # Cast shadow: the silhouette squashed onto the floor, thrown away from the light.
    if look.surface != "podium":
        sq = max(2, int(item.height * 0.16))
        flat = alpha.resize((item.width, sq), Image.LANCZOS)
        shear = -side * 1.4
        cast = flat.transform((int(item.width + abs(shear) * sq + 4), sq), Image.AFFINE,
                              (1, shear, -abs(shear) * sq if shear < 0 else 0, 0, 1, 0), Image.BILINEAR)
        cast = ImageOps.flip(cast)
        shadow = Image.new("L", size, 0)
        cx = x if shear < 0 else x - int(abs(shear) * sq)
        shadow.paste(cast, (cx, base_y - int(sq * 0.25)))
        shadow = shadow.filter(ImageFilter.GaussianBlur(unit * 0.012))
        arr = _over(arr, _layer(size, (8, 5, 3), shadow, 0.55 if look.mood in ("dark", "warm") else 0.32))
    # Contact shadow right under the base.
    contact = _aa_mask(size, lambda d, s: d.ellipse(((x + item.width * 0.06) * s, (base_y - unit * 0.012) * s,
                                                     (x + item.width * 0.94) * s, (base_y + unit * 0.012) * s),
                                                    fill=255), ss=2)
    contact = contact.filter(ImageFilter.GaussianBlur(unit * 0.008))
    arr = _over(arr, _layer(size, (5, 3, 2), contact, 0.8 if look.mood in ("dark", "warm") else 0.5))

    # Reflection on a glossy floor.
    if look.glossy and podium_h == 0:
        refl = ImageOps.flip(item)
        fade = np.linspace(0.30 if look.mood == "dark" else 0.22, 0, refl.height, dtype=np.float32) ** 1.4
        ra = (np.asarray(refl.getchannel("A"), np.float32) * fade[:, None]).astype(np.uint8)
        refl.putalpha(Image.fromarray(ra, "L"))
        refl = refl.filter(ImageFilter.GaussianBlur(unit * 0.003))
        layer = Image.new("RGBA", size, (0, 0, 0, 0))
        layer.alpha_composite(refl, (x, min(h - 1, base_y)))
        arr = _over(arr, layer)

    # The product itself: its own pixels, only nudged toward the scene light.
    lit = item.convert("RGB")
    lit = Image.blend(lit, Image.new("RGB", lit.size, _mix(pal.core, look.light, 0.5)), 0.06)
    # Rim light on the edge that faces the light.
    shift = max(2, int(unit * 0.006))
    moved = ImageChops.offset(alpha, -side * shift, shift // 2)
    rim = ImageChops.subtract(alpha, moved).filter(ImageFilter.GaussianBlur(max(1, shift * 0.6)))
    rim_strength = {"dark": 0.85, "warm": 0.8, "vivid": 0.5, "pastel": 0.35, "light": 0.3}[look.mood]
    rim_l = np.asarray(rim, np.float32)[..., None] / 255 * rim_strength
    lit_a = np.asarray(lit, np.float32) / 255
    lit_a = 1 - (1 - lit_a) * (1 - rim_l * np.array(_mix(look.light, (255, 255, 255), 0.4), np.float32) / 255)
    lit = _img(lit_a).convert("RGBA")
    lit.putalpha(alpha)
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    layer.alpha_composite(lit, (x, y))
    return _over(arr, layer)


def _podium(arr: np.ndarray, cx: int, top_y: int, width: int, height: int, pal: Palette, look: Look) -> np.ndarray:
    h, w, _ = arr.shape
    size = (w, h)
    ry = max(6, int(width * 0.12))
    base_col = _mix(pal.mid, (255, 255, 255), 0.55) if look.mood == "pastel" else _mix(pal.edge, (0, 0, 0), 0.25)
    if look.mood == "vivid":
        base_col = _mix(pal.mid, (255, 255, 255), 0.15)
    x0, x1 = cx - width // 2, cx + width // 2
    # floor shadow
    sh = _aa_mask(size, lambda d, s: d.ellipse(((x0 - width * 0.06) * s, (top_y + height - ry * 0.6) * s,
                                                (x1 + width * 0.12) * s, (top_y + height + ry * 1.3) * s), fill=255), ss=2)
    arr = _over(arr, _layer(size, (0, 0, 0), sh.filter(ImageFilter.GaussianBlur(width * 0.04)), 0.35))
    body = _aa_mask(size, lambda d, s: (d.rectangle((x0 * s, top_y * s, x1 * s, (top_y + height) * s), fill=255),
                                        d.ellipse((x0 * s, (top_y + height - ry) * s, x1 * s, (top_y + height + ry) * s),
                                                  fill=255)), ss=2)
    xs = np.linspace(-1, 1, w, dtype=np.float32)
    shade = np.clip(1 - 0.38 * (xs ** 2) + 0.12 * xs, 0.4, 1.1)  # cylinder shading
    col = np.array(base_col, np.float32) / 255 * shade[None, :, None] * 0.92
    col = np.broadcast_to(col, (h, w, 3))
    a = np.asarray(body, np.float32)[..., None] / 255
    arr = arr * (1 - a) + col * a
    top = _aa_mask(size, lambda d, s: d.ellipse((x0 * s, (top_y - ry) * s, x1 * s, (top_y + ry) * s), fill=255), ss=2)
    arr = _over(arr, _layer(size, _mix(base_col, (255, 255, 255), 0.22), top))
    rim = _aa_mask(size, lambda d, s: d.ellipse((x0 * s, (top_y - ry) * s, x1 * s, (top_y + ry) * s),
                                               outline=255, width=max(1, int(width * 0.006)) * s), ss=2)
    return _screen(arr, _layer(size, (255, 255, 255), rim, 0.45))


def _foreground(size, lay: Layout, pal: Palette, look: Look, rng: random.Random) -> Optional[Image.Image]:
    """A few large out-of-focus highlights in the corner near the light (away from the copy), for depth."""
    w, h = size
    unit = min(w, h)
    if look.mood == "light":
        return None
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    right = lay.light[0] >= w / 2
    d = ImageDraw.Draw(layer)
    for _ in range(3):
        r = unit * rng.uniform(0.05, 0.09)
        x = (w - rng.uniform(0, unit * 0.12)) if right else rng.uniform(0, unit * 0.12)
        y = rng.uniform(-unit * 0.04, unit * 0.16)
        d.ellipse((x - r, y - r, x + r, y + r), fill=_mix(pal.core, look.light, 0.5) + (int(rng.uniform(35, 70)),))
    return layer.filter(ImageFilter.GaussianBlur(unit * 0.02))


# --------------------------------------------------------------------------- typography
def _wrap(text: str, fnt, max_w: int) -> List[str]:
    lines, cur = [], ""
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if probe.textlength(_shape(trial), font=fnt) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    return lines + ([cur] if cur else [])


def _fit(text: str, kind: str, arabic: bool, start: int, max_w: int, max_h: int, max_lines: int, lead: float):
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    size = start
    while size > 18:
        fnt = font(kind, size, arabic)
        lines = _wrap(text, fnt, max_w)
        if (len(lines) <= max_lines and len(lines) * size * lead <= max_h
                and all(probe.textlength(_shape(l), font=fnt) <= max_w for l in lines)):
            return fnt, lines
        size = int(size * 0.93)
    fnt = font(kind, 18, arabic)
    return fnt, _wrap(text, fnt, max_w)[:max_lines]


def _text_mask(size, lines: List[str], fnt, x_anchor: int, y: int, align: str, lead: float) -> Tuple[Image.Image, int]:
    mask = Image.new("L", size, 0)
    d = ImageDraw.Draw(mask)
    step = int(fnt.size * lead)
    anchor = {"left": "la", "right": "ra", "center": "ma"}[align]
    for line in lines:
        d.text((x_anchor, y), _shape(line), font=fnt, fill=255, anchor=anchor)
        y += step
    return mask, y


def _gradient_fill(size, mask: Image.Image, top: RGB, bottom: RGB, box) -> Image.Image:
    w, h = size
    y0, y1 = box
    t = np.clip((np.arange(h, dtype=np.float32) - y0) / max(1, y1 - y0), 0, 1)[:, None, None]
    col = (np.array(top, np.float32) + (np.array(bottom, np.float32) - np.array(top, np.float32)) * t)
    col = np.broadcast_to(col, (h, w, 3)).astype(np.uint8)
    out = Image.fromarray(np.ascontiguousarray(col), "RGB").convert("RGBA")
    out.putalpha(mask)
    return out


def _draw_copy(canvas: Image.Image, lay: Layout, pal: Palette, look: Look, campaign: dict,
               headline: str, support: Optional[str], cta: Optional[str]) -> Image.Image:
    w, h = canvas.size
    unit = min(w, h)
    arabic = is_rtl(headline, support, cta)
    x0, y0, x1, y1 = lay.text_box
    box_w = x1 - x0
    objective = campaign.get("strategy_type") or ""
    kind = ("display" if look.serif else "sans_black")
    lead = 1.12 if look.serif else 1.08
    if arabic:
        lead = 1.45
    max_lines = 4 if not lay.stacked else 3
    head_cap = int(unit * (0.105 if not lay.stacked else (0.13 if lay.cta_bottom else 0.092)))
    head_room = int((y1 - y0) * (0.55 if not lay.stacked else 0.62))
    hfont, hlines = _fit(headline, kind, arabic, head_cap, box_w, head_room, max_lines, lead)

    show_support = bool(support) and (objective in ("STORYTELLING", "BRAND_AWARENESS", "INFLUENCER_STYLE", "SALES_DRIVEN", "")
                                      or not cta)
    sfont, slines = (None, [])
    if show_support:
        sfont, slines = _fit(support, "sans", arabic, int(unit * 0.027), int(box_w * 0.95), int(unit * 0.14), 3, 1.42)
    cfont = font("sans_semibold", unit * (0.030 if objective in ("SALES_DRIVEN", "URGENCY") else 0.026)
                 * (1.25 if lay.cta_bottom else 1.0), arabic)
    rule_h = int(unit * 0.05)

    head_h = int(len(hlines) * hfont.size * lead)
    sup_h = int(len(slines) * sfont.size * 1.42) if slines else 0
    cta_h = int(cfont.size * 2.6) if cta else 0
    gap = int(unit * 0.035)
    block = rule_h + head_h + (gap + sup_h if sup_h else 0) + ((gap * 1.4 + cta_h) if cta and not lay.cta_bottom else 0)
    if lay.stacked:
        top = y0 + max(0, ((y1 - y0) - block) // 2)
    else:
        top = y0 + max(0, int(((y1 - y0) - block) * 0.42))

    anchor_x = {"left": x0, "right": x1, "center": (x0 + x1) // 2}[lay.align]

    # Legibility scrim behind the copy (darkens dark looks, brightens light ones).
    scrim = Image.new("L", (w, h), 0)
    sd = ImageDraw.Draw(scrim)
    pad = int(unit * 0.06)
    sd.rounded_rectangle((x0 - pad * 2, top - pad, x1 + pad, top + block + pad), radius=pad * 2, fill=255)
    scrim = scrim.filter(ImageFilter.GaussianBlur(unit * 0.08))
    dark_text = _lum(pal.text) < 0.5
    arr = _f(canvas)
    scrim_col = (255, 255, 255) if dark_text else (10, 6, 3)
    scrim_amt = 0.35 if dark_text else (0.5 if look.mood != "vivid" else 0.32)
    arr = _over(arr, _layer((w, h), scrim_col, scrim, scrim_amt))
    canvas = _img(arr).convert("RGBA")

    # accent rule
    rule_w = int(unit * 0.06)
    rx = {"left": x0, "right": x1 - rule_w, "center": anchor_x - rule_w // 2}[lay.align]
    ImageDraw.Draw(canvas).rectangle((rx, top, rx + rule_w, top + max(2, int(unit * 0.0035))),
                                     fill=pal.accent if look.mood != "vivid" else pal.text)
    y = top + rule_h

    # headline: soft shadow, then the text; with 2+ lines the last line takes the accent colour
    mask, end_y = _text_mask((w, h), hlines, hfont, anchor_x, y, lay.align, lead)
    shadow = ImageChops.offset(mask, 0, max(1, int(unit * 0.003))).filter(ImageFilter.GaussianBlur(unit * 0.006))
    canvas.alpha_composite(_layer((w, h), (0, 0, 0) if not dark_text else (255, 255, 255), shadow,
                                  0.55 if not dark_text else 0.35))
    canvas.alpha_composite(_layer((w, h), pal.text, mask))
    if len(hlines) >= 2:
        last_y = y + int(hfont.size * lead) * (len(hlines) - 1)
        last_mask, _ = _text_mask((w, h), hlines[-1:], hfont, anchor_x, last_y, lay.align, lead)
        hi = pal.accent if look.mood not in ("vivid",) else _mix(pal.core, (255, 255, 255), 0.4)
        if look.mood in ("dark", "warm"):
            canvas.alpha_composite(_gradient_fill((w, h), last_mask, _mix(hi, (255, 255, 255), 0.45), hi,
                                                  (last_y, last_y + hfont.size)))
        elif look.mood != "vivid":
            canvas.alpha_composite(_layer((w, h), hi, last_mask))
    y = end_y

    if slines:
        y += gap - int(hfont.size * (lead - 1))
        smask, y = _text_mask((w, h), slines, sfont, anchor_x, y, lay.align, 1.42)
        canvas.alpha_composite(_layer((w, h), pal.text, smask, 0.86))

    if cta:
        text = _shape(cta)
        tw = int(ImageDraw.Draw(canvas).textlength(text, font=cfont))
        ch = int(cfont.size * 2.6)
        arrow = int(cfont.size * 1.1)
        cw = tw + arrow + int(cfont.size * 3.3)
        if lay.cta_bottom:
            cx0, cy0 = (w - cw) // 2, int(h * 0.885) - ch // 2
        else:
            cy0 = y + int(gap * 1.4) - (0 if not slines else int(gap * 0.2))
            cx0 = {"left": x0, "right": x1 - cw, "center": anchor_x - cw // 2}[lay.align]
        quiet = objective == "BRAND_AWARENESS"
        pill = _aa_mask((w, h), lambda d, s: d.rounded_rectangle((cx0 * s, cy0 * s, (cx0 + cw) * s, (cy0 + ch) * s),
                                                                 radius=ch // 2 * s, fill=255))
        sh = ImageChops.offset(pill, 0, int(unit * 0.01)).filter(ImageFilter.GaussianBlur(unit * 0.014))
        canvas.alpha_composite(_layer((w, h), (0, 0, 0), sh, 0.35))
        if quiet:  # outline button: the image, not the sale, leads
            ring = _aa_mask((w, h), lambda d, s: d.rounded_rectangle((cx0 * s, cy0 * s, (cx0 + cw) * s, (cy0 + ch) * s),
                                                                     radius=ch // 2 * s, outline=255,
                                                                     width=max(2, int(unit * 0.0028)) * s))
            canvas.alpha_composite(_layer((w, h), pal.text, pill, 0.10))
            canvas.alpha_composite(_layer((w, h), pal.text, ring))
            label_col = pal.text
        else:
            top_c = _mix(pal.accent, (255, 255, 255), 0.35) if look.mood in ("dark", "warm") else pal.accent
            canvas.alpha_composite(_gradient_fill((w, h), pill, top_c, _mix(pal.accent, (0, 0, 0), 0.12), (cy0, cy0 + ch)))
            label_col = pal.on_accent
        d = ImageDraw.Draw(canvas)
        rtl = lay.rtl or arabic
        pad_x = int(cfont.size * 1.3)
        if rtl:
            tx, ax = cx0 + cw - pad_x, cx0 + pad_x
            d.text((tx, cy0 + ch / 2), text, font=cfont, fill=label_col, anchor="rm")
        else:
            tx, ax = cx0 + pad_x, cx0 + cw - pad_x
            d.text((tx, cy0 + ch / 2), text, font=cfont, fill=label_col, anchor="lm")
        ay, aw, lw = cy0 + ch / 2, arrow * 0.9, max(2, int(cfont.size * 0.11))
        tip = (ax - (0 if not rtl else 0), ay)
        tail = (ax - aw, ay) if not rtl else (ax + aw, ay)
        head = aw * 0.38
        d.line((tail, tip), fill=label_col, width=lw)
        hx = tip[0] - head if not rtl else tip[0] + head
        d.line(((hx, ay - head), tip, (hx, ay + head)), fill=label_col, width=lw, joint="curve")
    return canvas


# --------------------------------------------------------------------------- render
def _finish(arr: np.ndarray, look: Look, nrng: np.random.Generator) -> np.ndarray:
    h, w, _ = arr.shape
    d = _radial(w, h, w * 0.5, h * 0.5, math.hypot(w, h) * 0.55)
    vig = np.clip((d - 0.55) / 0.5, 0, 1) ** 1.5
    amount = {"dark": 0.70, "warm": 0.72, "vivid": 0.40, "pastel": 0.14, "light": 0.16}[look.mood]
    arr = arr * (1 - vig[..., None] * amount)
    if look.mood == "warm":  # golden grade
        arr = arr * np.array([1.03, 1.0, 0.94], np.float32)
    arr = np.clip(arr, 0, 1)
    arr = arr + (arr - arr ** 2) * 0.10 * np.sign(arr - 0.5)  # gentle S-curve
    grain = nrng.normal(0, 0.012, (h, w, 1)).astype(np.float32)
    return np.clip(arr + grain, 0, 1)


def render_ad(campaign: dict, product: Optional[Image.Image] = None, size: Tuple[int, int] = (1080, 1080),
              image_format: Optional[str] = None, framed: bool = False) -> Image.Image:
    """The finished advertisement as an RGB image.

    `product` is the cut-out product (RGBA, transparent background) - or, with
    framed=True, an uncuttable photo already turned into a print by
    framed_photo(). None: a copy-led ad with no product drawn."""
    w, h = size
    unit = min(w, h)
    fmt = image_format or _format_of(size)
    look = choose_look(campaign)
    headline, support, cta = pick_copy(campaign)
    rtl = is_rtl(headline, support, cta)
    seed = zlib.crc32(str(campaign.get("campaign_id") or campaign.get("campaign_brief") or "").encode())
    rng, nrng = random.Random(seed), np.random.default_rng(seed)

    if product is not None:
        bbox = product.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()
        product = product.crop(bbox) if bbox else None
    aspect = (product.width / product.height) if product is not None else None
    lay = plan_layout(fmt, size, aspect, rtl)
    pal = make_palette(look, product if not framed else None)

    item = podium_w = podium_h = None
    podium_h = 0
    if product is not None:
        max_w, max_h = lay.product_max
        if look.surface == "podium" and not framed:
            podium_h = int(min(h * 0.11, max_h * 0.22))
            max_h -= podium_h
        item = _fit_product(product, (max_w, max_h))
        if look.surface == "podium" and not framed:
            podium_w = int(min(lay.product_max[0], max(item.width * 1.35, unit * 0.30)))
        lay.horizon = min(lay.horizon, lay.baseline - int(unit * 0.06)) if not podium_h else lay.baseline + podium_h // 2
        light_y = max(int(h * 0.12), lay.baseline - podium_h - item.height - int(unit * 0.02))
        if not lay.stacked:
            lay.light = (lay.light[0], light_y)
    lay.horizon = max(int(h * 0.45), min(lay.horizon, h - int(unit * 0.08)))

    arr = _backdrop(w, h, lay, pal, look)
    atmos = _atmosphere(size, lay, pal, look, rng)
    if atmos is not None:
        arr = _over(arr, atmos)
    if look.rays:
        arr = _screen(arr, _rays(size, lay, pal, rng))
    if look.bokeh:
        arr = _screen(arr, _bokeh(size, lay, pal, look, rng, lay.text_box))
    # the light source itself
    glow = Image.new("L", size, 0)
    lr = unit * (0.20 if look.mood in ("dark", "warm") else 0.35)
    ImageDraw.Draw(glow).ellipse((lay.light[0] - lr, lay.light[1] - lr, lay.light[0] + lr, lay.light[1] + lr), fill=255)
    arr = _screen(arr, _layer(size, _mix(pal.core, (255, 255, 255), 0.3),
                              glow.filter(ImageFilter.GaussianBlur(lr * 0.5)), 0.55))
    arr = _surface(arr, lay, pal, look, nrng)

    if item is not None:
        top_y = lay.baseline - podium_h
        x = lay.product_cx - item.width // 2
        if podium_h:
            arr = _podium(arr, lay.product_cx, lay.baseline - podium_h, podium_w, podium_h, pal, look)
        # on a podium the product stands on the near half of the top face, not on its back rim
        y = top_y - item.height + (int(podium_w * 0.12 * 0.45) if podium_h else 0)
        arr = _place_product(arr, item, x, y, lay, pal, look, podium_h)

    fg = _foreground(size, lay, pal, look, rng)
    if fg is not None:
        arr = _over(arr, fg)
    arr = _finish(arr, look, nrng)
    canvas = _draw_copy(_img(arr).convert("RGBA"), lay, pal, look, campaign, headline, support, cta)
    return canvas.convert("RGB")


def render_ad_bytes(campaign: dict, reference_image: Optional[bytes], size: Tuple[int, int],
                    image_format: Optional[str] = None) -> bytes:
    """PNG bytes. Cuts the product out of `reference_image` (transparent PNG,
    local background remover, or plain-backdrop key - product_composite.cutout);
    a photo that cannot be cut out is shown as a framed print; unreadable bytes
    are skipped. Never raises for a bad photo."""
    from src.ai.marketing import product_composite  # local: avoids an import cycle

    product, framed = None, False
    if reference_image:
        try:
            product, _ = product_composite.cutout(reference_image)
        except product_composite.CompositeError:
            try:
                photo = Image.open(io.BytesIO(reference_image))
                photo.load()
                product, framed = framed_photo(photo), True
            except Exception:  # noqa: BLE001 - unreadable photo: ad without it
                product = None
        except Exception:  # noqa: BLE001
            product = None
        if product is not None and max(product.size) > 2400:
            product.thumbnail((2400, 2400), Image.LANCZOS)
    image = render_ad(campaign, product, size, image_format, framed)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
