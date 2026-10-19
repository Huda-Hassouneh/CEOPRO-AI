"""Tests for the always-available designed poster (marketing/designed_poster.py): real PNG output,
product photo placement, Arabic copy, no invented text, deterministic."""
import io

import pytest
from PIL import Image, ImageDraw

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
