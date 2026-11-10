"""Tests for the art-directed advertisement composer (marketing/ad_composer.py):
every look x every format renders at the exact size; the look follows the
campaign's theme, else its objective; colours follow the product photo; the
layout adapts to format, product shape and text direction; the product's own
pixels are kept; only the campaign's own words are used; deterministic."""
import io

import numpy as np
import pytest
from PIL import Image, ImageDraw

from src.ai.marketing import ad_composer as ac
from src.ai.marketing.image_generation import IMAGE_FORMATS


def _campaign(**kw):
    base = {"campaign_id": "c-1", "campaign_brief": "Gift box", "creative_theme": "LUXURY_PREMIUM",
            "strategy_type": "SALES_DRIVEN",
            "content": {"INSTAGRAM": [{"headline": "Sweet moments, delivered",
                                       "body_copy": "Hand-packed every morning. Order by noon. #gifts",
                                       "cta": "Order now"}]}}
    base.update(kw)
    return base


def _product(colour=(200, 40, 40), size=(300, 420)):
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), 40, fill=colour + (255,))
    return img


def _png(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.parametrize("theme", [None, "CUSTOM", *ac.THEME_TO_LOOK])
@pytest.mark.parametrize("fmt", list(IMAGE_FORMATS))
def test_every_look_renders_every_format_at_its_exact_size(theme, fmt):
    size = IMAGE_FORMATS[fmt]["poster"]
    out = ac.render_ad(_campaign(creative_theme=theme), _product(), size, fmt)
    assert out.size == size and out.mode == "RGB"


def test_the_look_follows_the_theme_then_the_objective():
    assert ac.choose_look({"creative_theme": "MODERN_TECH", "strategy_type": "URGENCY"}).name == "tech"
    assert ac.choose_look({"creative_theme": "CUSTOM", "strategy_type": "URGENCY"}).name == "bold"
    assert ac.choose_look({"strategy_type": "STORYTELLING"}).name == "natural"
    assert ac.choose_look({}).name == "minimal"


def test_copy_comes_only_from_the_campaign():
    headline, support, cta = ac.pick_copy(_campaign())
    assert (headline, support, cta) == ("Sweet moments, delivered", "Hand-packed every morning.", "Order now")
    # a long first sentence is not squeezed onto the image, hashtags/emoji/links are dropped
    long_body = _campaign(content={"INSTAGRAM": [{"headline": "Hi 🎉 #new", "body_copy": "x " * 80, "cta": None}]})
    assert ac.pick_copy(long_body) == ("Hi", None, None)
    assert ac.pick_copy({"campaign_brief": "Olive oil\nmore"}) == ("Olive oil", None, None)
    assert ac.pick_copy({}) == ("New", None, None)


def test_the_scene_takes_its_colours_from_the_product():
    look = ac.LOOKS["luxury"]
    red, blue = ac.make_palette(look, _product((200, 40, 40))), ac.make_palette(look, _product((40, 70, 210)))
    assert red.mid != blue.mid
    assert red.mid[0] > red.mid[2] and blue.mid[2] > blue.mid[0]
    # vivid look: complementary backdrop so the product stands out
    vivid = ac.make_palette(ac.LOOKS["bold"], _product((220, 50, 30)))
    assert vivid.mid[2] > vivid.mid[0]


def test_the_layout_adapts_to_format_product_shape_and_direction():
    tall = ac.plan_layout("PORTRAIT", (1080, 1350), 0.5, rtl=False)
    assert not tall.stacked and tall.product_cx > 540 and tall.text_box[2] < tall.product_cx
    mirrored = ac.plan_layout("PORTRAIT", (1080, 1350), 0.5, rtl=True)
    assert mirrored.product_cx < 540 and mirrored.text_box[0] > mirrored.product_cx and mirrored.align == "right"
    assert ac.plan_layout("SQUARE", (1080, 1080), 2.0, rtl=False).stacked  # wide product: stacked
    assert ac.plan_layout("STORY", (1080, 1920), 0.6, rtl=False).stacked
    assert not ac.plan_layout("LANDSCAPE", (1920, 1080), 2.0, rtl=False).stacked


def test_the_products_own_pixels_are_kept():
    # a two-colour product: both colours must come through almost unchanged
    product = Image.new("RGBA", (300, 420), (0, 0, 0, 0))
    d = ImageDraw.Draw(product)
    d.rectangle((0, 0, 299, 209), fill=(30, 140, 60, 255))
    d.rectangle((0, 210, 299, 419), fill=(240, 220, 40, 255))
    out = np.asarray(ac.render_ad(_campaign(creative_theme="MINIMAL_CLEAN"), product, (1080, 1080), "SQUARE")).astype(int)
    for colour in ((30, 140, 60), (240, 220, 40)):
        close = (np.abs(out - np.array(colour)).max(axis=2) < 30).sum()
        assert close > 20_000, f"product colour {colour} lost"


def test_no_photo_means_no_product_is_drawn():
    with_product = ac.render_ad(_campaign(), _product((200, 40, 40)), (1080, 1080), "SQUARE")
    without = ac.render_ad(_campaign(), None, (1080, 1080), "SQUARE")
    reds = lambda im: ((np.asarray(im)[..., 0] > 150) & (np.asarray(im)[..., 2] < 90)).sum()  # noqa: E731
    assert reds(with_product) > 30_000 > reds(without)


def test_bytes_entry_point_handles_photos_and_bad_bytes():
    plain_backdrop = Image.new("RGB", (500, 700), (250, 250, 250))
    ImageDraw.Draw(plain_backdrop).rectangle((150, 100, 350, 650), fill=(40, 60, 160))
    busy = Image.effect_noise((400, 400), 90).convert("RGB")  # cannot be cut out: shown as a framed print
    for ref in (_png(plain_backdrop), _png(busy), b"not an image", None):
        out = Image.open(io.BytesIO(ac.render_ad_bytes(_campaign(), ref, (1080, 1350), "PORTRAIT")))
        assert out.format == "PNG" and out.size == (1080, 1350)


def test_arabic_copy_renders_right_to_left():
    campaign = _campaign(content={"INSTAGRAM": [{"headline": "حلويات طازجة كل يوم", "cta": "اطلب الآن"}]})
    assert ac.is_rtl(*ac.pick_copy(campaign))
    assert ac.render_ad(campaign, _product(), (1080, 1350), "PORTRAIT").size == (1080, 1350)


def test_same_campaign_gives_the_same_advert():
    a = ac.render_ad_bytes(_campaign(), _png(_product()), (1080, 1080), "SQUARE")
    assert a == ac.render_ad_bytes(_campaign(), _png(_product()), (1080, 1080), "SQUARE")
