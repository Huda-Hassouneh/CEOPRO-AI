"""The real product photo is placed into the picture on our server: cut out
(transparent PNG, local remover, or a plain studio backdrop), the model makes
only the scene from text, and the photo never reaches a provider."""
import io
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image, ImageDraw

from src.ai.marketing import image_generation, image_service, product_composite


def _png(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _bottle_on_white():
    picture = Image.new("RGB", (600, 800), (247, 247, 245))
    draw = ImageDraw.Draw(picture)
    draw.rounded_rectangle((220, 220, 380, 760), radius=40, fill=(60, 95, 35))
    draw.rectangle((270, 120, 330, 230), fill=(55, 88, 32))
    return _png(picture)


def _scene(size=(1080, 1080)):
    scene = Image.new("RGB", size, (200, 170, 120))
    ImageDraw.Draw(scene).rectangle((0, size[1] * 3 // 4, size[0], size[1]), fill=(120, 80, 50))
    return scene


def test_a_transparent_png_is_used_as_it_is():
    jar = Image.new("RGBA", (400, 500), (0, 0, 0, 0))
    ImageDraw.Draw(jar).rectangle((100, 100, 300, 450), fill=(210, 140, 30, 255))
    product, how = product_composite.cutout(_png(jar))
    assert how == "transparent" and product.size == (201, 351)


def test_a_product_on_a_plain_studio_backdrop_is_keyed_out():
    product, how = product_composite.cutout(_bottle_on_white())
    assert how == "plain-backdrop"
    assert abs(product.width - 161) <= 4 and abs(product.height - 641) <= 4
    assert product.getpixel((2, 2))[3] == 0, "the backdrop corner is transparent"
    assert product.getpixel((product.width // 2, product.height - 50))[3] == 255, "the product is kept"


def test_a_busy_background_is_refused_rather_than_guessed():
    noisy = Image.effect_noise((600, 600), 90).convert("RGB")
    with pytest.raises(product_composite.CompositeError):
        product_composite.cutout(_png(noisy))


@pytest.mark.parametrize("image_format,size", [("SQUARE", (1080, 1080)), ("STORY", (1080, 1920)), ("WIDE", (1200, 628))])
def test_the_product_is_placed_whole_and_unchanged_in_shape(image_format, size):
    product, _ = product_composite.cutout(_bottle_on_white())
    out = product_composite.composite(_scene(size), product, image_format)
    assert out.size == size
    # The product's own green is in the middle of the picture; the scene colour is at the corner.
    centre = out.getpixel((size[0] // 2, int(size[1] * 0.6)))
    assert centre[1] > centre[0] and centre[1] > centre[2]
    assert out.getpixel((5, 5)) == (200, 170, 120)


def test_the_scene_prompt_asks_for_an_empty_centre_and_never_carries_the_photo():
    prompt = product_composite.scene_prompt("Olive oil 1L", "warm kitchen, wooden table, morning light")
    assert "Olive oil 1L" in prompt and "no product" in prompt and "warm kitchen" in prompt
    shaped = image_generation.shape_prompt(prompt, "STORY", scene=True)
    assert "centre of the frame and the surface in front are empty" in shaped
    assert "whole product is clearly visible" not in shaped


def test_with_a_photo_the_model_gets_text_only_and_the_real_product_is_composited():
    calls = []

    def fake_generate(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return image_generation.GeneratedImage(content=_png(_scene()), content_type="image/png", provider="cloudflare", model="m")

    with patch.object(image_generation, "generate_campaign_image", side_effect=fake_generate):
        image = image_service.generate_with_real_product(
            {"campaign_id": "c1", "campaign_brief": "Olive oil 1L", "creative_direction": "rustic kitchen"},
            _bottle_on_white(), "SQUARE", seed=3)
    assert image.used_reference is True and image.mode == "ai" and image.provider == "cloudflare"
    assert "not sent" in image.reference_note
    (prompt, kwargs), = calls
    assert kwargs.get("scene") is True and "reference_image" not in kwargs, "the photo is never passed to a provider"
    assert "Olive oil 1L" in prompt


def test_with_no_scene_model_a_designed_background_still_shows_the_real_product():
    with patch.object(image_generation, "generate_campaign_image",
                      side_effect=image_generation.ImageGenerationError("NOT_CONFIGURED", "none")):
        image = image_service.generate_with_real_product({"campaign_id": "c1", "campaign_brief": "Oil"}, _bottle_on_white(), "STORY")
    assert image.mode == "designed" and image.used_reference is True
    assert (image.width, image.height) == (1080, 1920)


def test_a_white_label_inside_the_product_is_not_keyed_out():
    picture = Image.new("RGB", (600, 800), (255, 255, 255))
    draw = ImageDraw.Draw(picture)
    draw.rounded_rectangle((200, 200, 400, 760), radius=30, fill=(200, 80, 110))
    draw.rectangle((230, 400, 370, 600), fill=(255, 255, 255))  # white label, same colour as the backdrop
    product, how = product_composite.cutout(_png(picture))
    assert how == "plain-backdrop"
    label = product.crop((60, 230, 140, 370)).getchannel("A")  # cut-out is cropped to the product box
    assert label.getextrema()[0] > 240, "the label must stay part of the product"


def test_with_no_scene_model_the_designed_picture_is_a_full_advert():
    campaign = {"campaign_id": "c1", "campaign_brief": "Oil", "creative_theme": "LIFESTYLE",
                "content": {"INSTAGRAM": [{"headline": "Fresh from the grove", "cta": "Shop"}]}}
    with patch.object(image_generation, "generate_campaign_image",
                      side_effect=image_generation.ImageGenerationError("NOT_CONFIGURED", "none")):
        image = image_service.generate_with_real_product(campaign, _bottle_on_white(), "PORTRAIT")
    assert image.mode == "designed" and (image.width, image.height) == (1080, 1350)
    picture = Image.open(io.BytesIO(image.content)).convert("RGB")
    px = np.asarray(picture).astype(int)
    greens = ((px[..., 1] > px[..., 0] + 15) & (px[..., 1] > px[..., 2] + 25) & (px[..., 1] > 60)).sum()
    assert greens > 10_000, "the real green bottle is in the picture"


def test_an_unusable_photo_falls_back_to_the_normal_picture():
    noisy = Image.effect_noise((400, 400), 90).convert("RGB")
    assert image_service.generate_with_real_product({"campaign_id": "c1"}, _png(noisy), "SQUARE") is None
