"""
KEEL - Automated Marketing: "designed" poster (always-available fallback).

When every AI image provider is out of free allowance, rate limited or down,
the Studio still returns a finished, watermark-free image instead of an error:
a locally drawn, style-matched backdrop with the campaign's own headline and
call to action, and - when the tenant selected one - their real product photo
(background-removed if it was processed) placed on it. Unlimited and free
(Pillow only, no network, no key); it is what guarantees the weekly image
volume does not depend on any provider's free quota.

Honesty: this is NOT AI-generated, and the result says so
(image_generation_mode: "designed"). Only text the campaign already has is
drawn (its headline / CTA) - nothing is invented. Arabic text is shaped with
arabic-reshaper + python-bidi (DejaVu Sans, which has Arabic glyphs).
"""
import io
import os
import random
import zlib
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

try:  # Arabic shaping; both are in requirements.txt
    import arabic_reshaper
    from bidi.algorithm import get_display
except ImportError:  # pragma: no cover
    arabic_reshaper = get_display = None

SIZE: Tuple[int, int] = (1080, 1080)


@dataclass(frozen=True)
class StylePreset:
    # Background gradient (top colour, bottom colour), headline text colour,
    # accent (badge / CTA) colour, and the text colour used on the accent.
    top: Tuple[int, int, int]
    bottom: Tuple[int, int, int]
    text: Tuple[int, int, int]
    accent: Tuple[int, int, int]
    on_accent: Tuple[int, int, int]
    scene: str = ''


STYLES: Dict[str, StylePreset] = {
    "minimal": StylePreset((250, 250, 248), (226, 228, 232), (28, 30, 36), (28, 30, 36), (255, 255, 255),
                           "clean seamless light-grey studio backdrop, soft shadow, lots of empty space"),
    "bold": StylePreset((255, 196, 0), (255, 120, 0), (20, 20, 20), (20, 20, 20), (255, 214, 10),
                        "vivid orange-yellow gradient backdrop, high contrast, energetic"),
    "luxury": StylePreset((34, 30, 28), (10, 9, 9), (240, 222, 180), (201, 166, 94), (20, 16, 10),
                          "dark marble surface, warm gold rim light, premium editorial look"),
    "playful": StylePreset((255, 214, 232), (186, 230, 253), (60, 40, 110), (255, 90, 140), (255, 255, 255),
                           "pastel gradient backdrop with soft confetti shapes, cheerful"),
    "natural": StylePreset((240, 244, 226), (196, 214, 170), (38, 62, 34), (62, 110, 52), (255, 255, 255),
                           "soft daylight on a natural light-wood surface with green leaves"),
}



def _blur(img: Image.Image, r: float) -> Image.Image:
    return img.filter(ImageFilter.GaussianBlur(r))


def procedural_scene(style: str, size: Tuple[int, int], seed: int = 0) -> Image.Image:
    """Deterministic, offline, style-specific background (never contains text)."""
    rng = random.Random(seed)
    w, h = size
    st = STYLES.get(style, STYLES['minimal'])
    base = Image.new("RGB", size)
    column = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        column.putpixel((0, y), tuple(int(st.top[i] + (st.bottom[i] - st.top[i]) * t) for i in range(3)))
    base = column.resize(size)
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    m = min(w, h)

    if style == "minimal":
        # Soft overhead light pool + a faint floor line.
        d.ellipse((w * 0.1, h * 0.05, w * 0.9, h * 0.75), fill=(255, 255, 255, 150))
        d.rectangle((0, int(h * 0.78), w, h), fill=(0, 0, 0, 22))
        layer = _blur(layer, m * 0.08)
    elif style == "bold":
        cx, cy = w / 2, h * 0.55
        for k in range(18):  # light rays
            a0 = k * 20
            d.pieslice((cx - w, cy - w, cx + w, cy + w), a0, a0 + 10, fill=(255, 255, 255, 46))
        for _ in range(7):
            r = rng.randint(int(m * 0.05), int(m * 0.18))
            x, y = rng.randint(0, w), rng.randint(0, h)
            d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, rng.randint(30, 70)))
        layer = _blur(layer, 2)
    elif style == "luxury":
        d.ellipse((w * 0.15, h * 0.2, w * 0.85, h * 0.85), fill=st.accent + (70,))
        layer = _blur(layer, m * 0.12)
        veins = Image.new("RGBA", size, (0, 0, 0, 0))
        vd = ImageDraw.Draw(veins)
        for _ in range(9):  # marble veins
            x, y = rng.randint(0, w), rng.randint(0, h)
            pts = [(x, y)]
            for _ in range(8):
                x += rng.randint(-int(w * 0.12), int(w * 0.12))
                y += rng.randint(int(h * 0.03), int(h * 0.1))
                pts.append((x, y))
            vd.line(pts, fill=st.accent + (55,), width=max(1, m // 400))
        layer = Image.alpha_composite(layer, _blur(veins, 1.2))
        bokeh = Image.new("RGBA", size, (0, 0, 0, 0))
        bd = ImageDraw.Draw(bokeh)
        for _ in range(14):
            r = rng.randint(int(m * 0.01), int(m * 0.04))
            x, y = rng.randint(0, w), rng.randint(0, h)
            bd.ellipse((x - r, y - r, x + r, y + r), fill=st.accent + (rng.randint(40, 110),))
        layer = Image.alpha_composite(layer, _blur(bokeh, 2.5))
    elif style == "playful":
        colors = [(255, 90, 140), (255, 200, 60), (90, 190, 255), (150, 110, 255), (90, 220, 170)]
        for _ in range(34):
            r = rng.randint(int(m * 0.015), int(m * 0.05))
            x, y = rng.randint(0, w), rng.randint(0, h)
            c = rng.choice(colors) + (rng.randint(110, 190),)
            shape = rng.choice(("c", "r", "t"))
            if shape == "c":
                d.ellipse((x - r, y - r, x + r, y + r), fill=c)
            elif shape == "r":
                d.rounded_rectangle((x - r, y - r, x + r, y + r), radius=r // 3, fill=c)
            else:
                d.polygon([(x, y - r), (x - r, y + r), (x + r, y + r)], fill=c)
        layer = _blur(layer, 1)
    else:  # natural
        greens = [(62, 110, 52), (96, 150, 70), (130, 180, 90), (40, 90, 60)]
        for _ in range(16):  # soft out-of-focus leaves
            lw, lh = rng.randint(int(m * 0.08), int(m * 0.22)), rng.randint(int(m * 0.2), int(m * 0.5))
            x = rng.choice((rng.randint(-lw, int(w * 0.25)), rng.randint(int(w * 0.75), w)))
            y = rng.randint(-lh // 2, h)
            leaf = Image.new("RGBA", (lw * 2, lh * 2), (0, 0, 0, 0))
            ImageDraw.Draw(leaf).ellipse((lw // 2, 0, lw * 3 // 2, lh * 2), fill=rng.choice(greens) + (150,))
            layer.alpha_composite(leaf.rotate(rng.randint(0, 360), expand=False), (max(0, x), max(0, y)))
        d.polygon([(w * 0.5 - m * 0.1, 0), (w * 0.5 + m * 0.35, 0), (w * 0.5 + m * 0.1, h), (w * 0.5 - m * 0.4, h)],
                  fill=(255, 255, 230, 40))  # sunbeam
        d.rectangle((0, int(h * 0.8), w, h), fill=(150, 110, 70, 60))  # wood surface
        layer = _blur(layer, m * 0.012)

    out = Image.alpha_composite(base.convert("RGBA"), layer).convert("RGB")
    # fine grain avoids gradient banding and reads as photographic
    noise = np.random.default_rng(seed).normal(0, 2.2, (h, w, 1))
    arr = np.clip(np.asarray(out).astype(np.float32) + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)




THEME_TO_STYLE = {
    "LUXURY_PREMIUM": "luxury", "MINIMAL_CLEAN": "minimal", "MODERN_TECH": "minimal",
    "SOCIAL_TRENDY": "playful", "BOLD_PROMOTIONAL": "bold", "LIFESTYLE": "natural", "SEASONAL": "playful",
}
_ARABIC = __import__("re").compile(r"[؀-ۿ]")
_FONTS = (
    os.getenv("MARKETING_FONT_PATH", ""),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
)


def _font(size: int):
    for path in _FONTS:
        if path and os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def _shape(text: str) -> str:
    if text and _ARABIC.search(text) and arabic_reshaper and get_display:
        return get_display(arabic_reshaper.reshape(text))
    return text


def pick_copy(campaign: dict) -> Tuple[str, Optional[str]]:
    """(headline, cta) from the campaign's own generated content, else its brief. Nothing invented."""
    content = campaign.get("content") or {}
    for platform in ("INSTAGRAM", "FACEBOOK", *content):
        for variant in content.get(platform) or []:
            if (variant.get("headline") or "").strip():
                cta = (variant.get("cta") or "").strip() or None
                return variant["headline"].strip()[:60], (cta[:30] if cta else None)
    brief = (campaign.get("campaign_brief") or "").strip().splitlines()
    return (brief[0][:60] if brief and brief[0] else "New"), None


def _wrap(draw, text, font, max_width):
    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if draw.textlength(_shape(trial), font=font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    return lines + ([current] if current else [])


def _fit(draw, text, start, max_width, max_lines):
    size = start
    while size > 22:
        font = _font(size)
        lines = _wrap(draw, text, font, max_width)
        if len(lines) <= max_lines and all(draw.textlength(_shape(l), font=font) <= max_width for l in lines):
            return font, lines
        size -= 4
    font = _font(22)
    return font, _wrap(draw, text, font, max_width)[:max_lines]


def _product_layer(photo: Image.Image, box: Tuple[int, int]) -> Image.Image:
    photo = photo.convert("RGBA")
    transparent = (np.asarray(photo.getchannel("A")) < 250).mean() > 0.01
    if not transparent:  # an unprocessed photo goes on a rounded white card
        pad = int(min(photo.size) * 0.04)
        card = Image.new("RGBA", (photo.width + 2 * pad, photo.height + 2 * pad), (0, 0, 0, 0))
        mask = Image.new("L", card.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, *card.size), radius=pad * 3, fill=255)
        card.paste((255, 255, 255, 255), mask=mask)
        inner = Image.new("L", photo.size, 0)
        ImageDraw.Draw(inner).rounded_rectangle((0, 0, *photo.size), radius=pad * 2, fill=255)
        card.paste(photo.convert("RGB"), (pad, pad), inner)
        photo = card
    scale = min(box[0] / photo.width, box[1] / photo.height)
    return photo.resize((max(1, int(photo.width * scale)), max(1, int(photo.height * scale))), Image.LANCZOS)


def render_designed_poster(campaign: dict, reference_image: Optional[bytes] = None) -> bytes:
    """PNG bytes of the designed poster. Never raises for a bad reference photo (it is just skipped)."""
    style_name = THEME_TO_STYLE.get(campaign.get("creative_theme") or "", "minimal")
    st = STYLES[style_name]
    width, height = SIZE
    seed = zlib.crc32(str(campaign.get("campaign_id") or campaign.get("campaign_brief") or "").encode())
    canvas = procedural_scene(style_name, SIZE, seed).convert("RGBA")
    headline, cta = pick_copy(campaign)
    margin = int(width * 0.07)
    draw = ImageDraw.Draw(canvas)
    head_font, head_lines = _fit(draw, headline, int(width * 0.095), width - 2 * margin, 3)
    head_h = margin + int(len(head_lines) * head_font.size * 1.18)
    cta_font = _font(int(width * 0.04))
    foot_h = (int(cta_font.size * 1.9) + margin) if cta else margin
    product = None
    if reference_image:
        try:
            photo = Image.open(io.BytesIO(reference_image))
            photo.load()
            if max(photo.size) > 2048:
                photo.thumbnail((2048, 2048), Image.LANCZOS)
            product = _product_layer(photo, (width - 2 * margin, max(120, height - head_h - foot_h - margin // 2)))
        except Exception:  # noqa: BLE001 - unreadable photo: poster without it
            product = None
    if product is not None:
        px, py = (width - product.width) // 2, head_h + (height - head_h - foot_h - product.height) // 2
        shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        sil = Image.new("RGBA", product.size, (0, 0, 0, 110))
        sil.putalpha(product.getchannel("A").point(lambda v: int(v * 0.43)))
        shadow.paste(sil, (px, py + int(product.height * 0.03)), sil)
        canvas = Image.alpha_composite(canvas, shadow.filter(ImageFilter.GaussianBlur(width // 70)))
        canvas.alpha_composite(product, (px, py))
        draw = ImageDraw.Draw(canvas)
        y = margin
    else:  # no product photo: headline sits in the optical centre
        y = (height - len(head_lines) * int(head_font.size * 1.18)) // 2 - (foot_h // 3)
    for line in head_lines:
        draw.text((width / 2, y), _shape(line), font=head_font, fill=st.text, anchor="ma")
        y += int(head_font.size * 1.18)
    if cta:
        text = _shape(cta)
        w = int(draw.textlength(text, font=cta_font)) + int(width * 0.08)
        h = int(cta_font.size * 1.9)
        x0, y0 = (width - w) // 2, height - margin - h
        draw.rounded_rectangle((x0, y0, x0 + w, y0 + h), radius=h // 2, fill=st.accent)
        draw.text((width / 2, y0 + h / 2), text, font=cta_font, fill=st.on_accent, anchor="mm")
    buffer = io.BytesIO()
    canvas.convert("RGB").save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
