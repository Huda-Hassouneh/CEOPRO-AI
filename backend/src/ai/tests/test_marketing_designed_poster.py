"""Tests for the always-available designed poster (marketing/designed_poster.py): real PNG output,
product photo placement, Arabic copy, no invented text, deterministic."""
import io
import os

import pytest
from PIL import Image, ImageDraw, ImageFont

from src.ai.marketing import designed_poster as dp


def _png(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _campaign(**kw):
    base = {"campaign_id": "c-1", "campaign_brief": "Kunafa gift box", "creative_theme": "LUXURY_PREMIUM",
            "content": {"INSTAGRAM": [{"headline": "Sweet moments, delivered", "cta": "Order now"}]}}
    base.update(kw)
    return base


def _cutout():
    img = Image.new("RGBA", (300, 400), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((0, 0, 299, 399), 50, fill=(200, 60, 40, 255))
    return _png(img)


@pytest.mark.parametrize("theme", [None, "CUSTOM", *dp.THEME_TO_STYLE])
def test_every_theme_renders_a_square_png(theme):
    out = dp.render_designed_poster(_campaign(creative_theme=theme))
    image = Image.open(io.BytesIO(out))
    assert image.format == "PNG" and image.size == (1080, 1080)


def test_copy_comes_only_from_the_campaign():
    assert dp.pick_copy(_campaign()) == ("Sweet moments, delivered", "Order now")
    assert dp.pick_copy({"campaign_brief": "Olive oil\nsecond line"}) == ("Olive oil", None)
    assert dp.pick_copy({}) == ("New", None)  # nothing invented beyond a neutral word


def test_product_photo_is_placed_on_the_poster():
    plain = Image.open(io.BytesIO(dp.render_designed_poster(_campaign()))).convert("RGB")
    with_product = Image.open(io.BytesIO(dp.render_designed_poster(_campaign(), _cutout()))).convert("RGB")
    assert with_product.getpixel((540, 540))[0] > 150 > with_product.getpixel((540, 540))[2]  # the red product
    assert plain.getpixel((540, 540)) != with_product.getpixel((540, 540))


def test_opaque_photo_goes_on_a_card_and_bad_bytes_are_skipped():
    photo = _png(Image.new("RGB", (400, 300), (10, 120, 200)))
    assert Image.open(io.BytesIO(dp.render_designed_poster(_campaign(), photo))).size == (1080, 1080)
    assert Image.open(io.BytesIO(dp.render_designed_poster(_campaign(), b"not an image"))).size == (1080, 1080)


def test_arabic_copy_is_shaped_and_renders():
    campaign = _campaign(content={"INSTAGRAM": [{"headline": "حلويات طازجة كل يوم", "cta": "اطلب الآن"}]})
    assert dp._shape("اطلب") != "اطلب"  # reshaped + reordered for display
    assert Image.open(io.BytesIO(dp.render_designed_poster(campaign, _cutout()))).size == (1080, 1080)


def test_same_campaign_gives_the_same_poster():
    assert dp.render_designed_poster(_campaign()) == dp.render_designed_poster(_campaign())


def _ink(text, size=80):
    """Greyscale ink of `text` drawn the way the poster draws it (shaped, then drawn with _font), trimmed
    horizontally only so that vertical positions stay comparable between a phrase and one of its words."""
    font = dp._font(size)
    canvas = Image.new("L", (1600, 220), 0)
    ImageDraw.Draw(canvas).text((20, 20), dp._shape(text), font=font, fill=255)
    left, _, right, _ = canvas.getbbox()
    return canvas.crop((left, 0, right, canvas.height))


def _right_part_matches(phrase, first_word):
    """True when the first logical word is drawn at the right-hand end of the phrase (right-to-left)."""
    whole, word = _ink(phrase), _ink(first_word)
    right = whole.crop((whole.width - word.width, 0, whole.width, whole.height))
    differing = sum(1 for a, b in zip(right.tobytes(), word.tobytes()) if abs(a - b) > 96)
    return differing / (right.width * right.height) < 0.02


def test_fonts_use_basic_layout_so_a_raqm_pillow_does_not_reorder_twice():
    # _shape() already reorders RTL text; a Raqm layout (the Docker image's Pillow) would reverse it again.
    font = dp._font(40)
    if not hasattr(font, "layout_engine"):
        pytest.skip("no TrueType font available, Pillow's bitmap fallback is in use")
    assert font.layout_engine == ImageFont.Layout.BASIC


@pytest.mark.parametrize("phrase,first_word", [
    ("عرض خاص", "عرض"),                 # Arabic only: first word is the rightmost
    ("خصم Latte", "خصم"),              # Arabic first, then Latin
    ("Latte اليوم فقط", "Latte"),      # a wrapped line that STARTS with Latin must still be RTL
])
def test_arabic_word_order_is_right_to_left(phrase, first_word):
    if not any(p and os.path.isfile(p) for p in dp._FONTS):
        pytest.skip("no Arabic-capable TrueType font installed")
    assert _right_part_matches(phrase, first_word)
