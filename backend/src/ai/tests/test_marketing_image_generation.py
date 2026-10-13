"""
Unit tests for src/ai/marketing/image_generation.py - the HTTP calls to
each provider are mocked at the httpx boundary with the response shapes
those providers document (Cloudflare's JSON with a base64 image,
Hugging Face's and Pollinations' raw image bytes, their 429s and JSON
errors). This verifies the request building, parsing, image checks and
the fallback between providers; it does NOT verify a provider's live
behavior - this sandbox's network policy blocks every image provider.
"""
import base64
import io
from unittest.mock import MagicMock, patch

import httpx
import pytest
from PIL import Image

from src.ai.marketing import image_generation
from src.ai.marketing.image_generation import (
    GeneratedImage, ImageGenerationError, build_image_prompt,
    generate_campaign_image, get_image_generation_capability, provider_chain,
)


def _picture(size=1024, fmt="PNG"):
    buffer = io.BytesIO()
    Image.new("RGB", (size, size), (200, 120, 40)).save(buffer, format=fmt)
    return buffer.getvalue()


PNG = _picture()
JPEG = _picture(fmt="JPEG")


def _response(status=200, content=b"", content_type="image/png", json_body=None, headers=None):
    response = MagicMock()
    response.status_code = status
    response.headers = {"content-type": content_type, **(headers or {})}
    response.content = content
    response.text = content.decode("latin-1")[:300] if isinstance(content, bytes) else str(content)
    response.json = MagicMock(return_value=json_body) if json_body is not None else MagicMock(side_effect=ValueError("no json"))
    return response


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("MARKETING_IMAGE_PROVIDER", "MARKETING_IMAGE_PROVIDERS", "MARKETING_IMAGE_KEYLESS", "HUGGINGFACE_API_TOKEN",
                 "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    cooling = set()
    monkeypatch.setattr(image_generation, "_cooling_down", lambda name: name in cooling)
    monkeypatch.setattr(image_generation, "_cool_down", lambda name, seconds: cooling.add(name))
    return cooling


# --- build_image_prompt -----------------------------------------------

def test_build_image_prompt_combines_brief_and_stripped_creative_direction():
    campaign = {
        "campaign_brief": "Product name: Widget",
        "creative_direction": "A clean minimal product shot. No image or video has been generated from this brief yet.",
    }
    prompt = build_image_prompt(campaign)
    assert "Widget" in prompt
    assert "clean minimal product shot" in prompt
    assert "No image or video has been generated" not in prompt


def test_build_image_prompt_falls_back_when_both_fields_empty():
    prompt = build_image_prompt({"campaign_brief": None, "creative_direction": None})
    assert prompt == "A professional product advertisement photo."


def test_build_image_prompt_truncates_to_max_length():
    campaign = {"campaign_brief": "x" * 3000, "creative_direction": ""}
    prompt = build_image_prompt(campaign)
    assert len(prompt) <= 2000


# --- which providers, in which order ---------------------------------

def test_by_default_free_providers_with_keys_come_first_then_the_keyless_one(monkeypatch):
    assert provider_chain() == ["pollinations"]
    monkeypatch.setenv("HUGGINGFACE_API_TOKEN", "hf")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf")
    assert provider_chain() == ["cloudflare", "huggingface", "pollinations"]
    monkeypatch.setenv("MARKETING_IMAGE_KEYLESS", "false")
    assert provider_chain() == ["cloudflare", "huggingface"]
    monkeypatch.setenv("MARKETING_IMAGE_PROVIDERS", "pollinations, huggingface")
    assert provider_chain() == ["pollinations", "huggingface"]
    monkeypatch.setenv("MARKETING_IMAGE_PROVIDERS", "none")
    assert provider_chain() == []


def test_the_older_single_provider_setting_still_works(monkeypatch):
    monkeypatch.setenv("MARKETING_IMAGE_PROVIDER", "huggingface")
    assert provider_chain() == ["huggingface"]
    monkeypatch.setenv("MARKETING_IMAGE_PROVIDER", "none")
    assert provider_chain() == []


def test_nothing_enabled_is_not_configured(monkeypatch):
    monkeypatch.setenv("MARKETING_IMAGE_PROVIDERS", "none")
    with pytest.raises(ImageGenerationError) as exc:
        generate_campaign_image("a prompt")
    assert exc.value.status == "NOT_CONFIGURED"
    assert get_image_generation_capability()["available"] is False


def test_unknown_provider_and_empty_prompt():
    with pytest.raises(ImageGenerationError) as exc:
        generate_campaign_image("a prompt", provider="not-a-real-provider")
    assert exc.value.status == "NOT_CONFIGURED"
    with pytest.raises(ImageGenerationError) as exc:
        generate_campaign_image("   ", provider="pollinations")
    assert exc.value.status == "PROVIDER_ERROR"


# --- each provider ----------------------------------------------------

def test_cloudflare_returns_the_decoded_image(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf-token")
    body = {"result": {"image": base64.b64encode(JPEG).decode()}, "success": True, "errors": [], "messages": []}
    with patch("src.ai.marketing.image_generation.httpx.post", return_value=_response(json_body=body, content_type="application/json")) as post:
        image = generate_campaign_image("kunafa on a tray", provider="cloudflare")
    url = post.call_args.args[0]
    assert url == "https://api.cloudflare.com/client/v4/accounts/acc/ai/run/@cf/black-forest-labs/flux-1-schnell"
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer cf-token"
    assert post.call_args.kwargs["json"] == {"prompt": "kunafa on a tray", "steps": 4}
    assert image.provider == "cloudflare" and image.content == JPEG and image.content_type == "image/jpeg"
    assert (image.width, image.height) == (1024, 1024)


def test_cloudflare_error_body_is_a_provider_error(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf")
    body = {"result": None, "success": False, "errors": [{"code": 10000, "message": "Authentication error"}]}
    with patch("src.ai.marketing.image_generation.httpx.post", return_value=_response(403, json_body=body, content_type="application/json")):
        with pytest.raises(ImageGenerationError) as exc:
            generate_campaign_image("x", provider="cloudflare")
    assert exc.value.status == "PROVIDER_ERROR"


def test_huggingface_and_pollinations_return_raw_image_bytes(monkeypatch):
    monkeypatch.setenv("HUGGINGFACE_API_TOKEN", "hf")
    with patch("src.ai.marketing.image_generation.httpx.post", return_value=_response(content=PNG)) as post:
        image = generate_campaign_image("x", provider="huggingface")
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer hf" and image.content_type == "image/png"
    with patch("src.ai.marketing.image_generation.httpx.get", return_value=_response(content=JPEG, content_type="image/jpeg")) as get:
        image = generate_campaign_image("kunafa & tea", provider="pollinations")
    assert get.call_args.args[0].endswith("/kunafa%20%26%20tea")
    params = get.call_args.kwargs["params"]
    assert params["nologo"] == "true" and params["private"] == "true" and "seed" in params
    assert image.provider == "pollinations" and image.content_type == "image/jpeg"


def test_an_error_page_served_as_an_image_is_not_kept(monkeypatch):
    with patch("src.ai.marketing.image_generation.httpx.get", return_value=_response(content=b"<html>busy</html>", content_type="image/jpeg")):
        with pytest.raises(ImageGenerationError) as exc:
            generate_campaign_image("x", provider="pollinations")
    assert "not an image" in exc.value.message
    with patch("src.ai.marketing.image_generation.httpx.get", return_value=_response(content=_picture(64), content_type="image/png")):
        with pytest.raises(ImageGenerationError) as exc:
            generate_campaign_image("x", provider="pollinations")
    assert "too small" in exc.value.message


def test_huggingface_json_error_and_missing_token(monkeypatch):
    with pytest.raises(ImageGenerationError) as exc:
        generate_campaign_image("x", provider="huggingface")
    assert exc.value.status == "NOT_CONFIGURED"
    monkeypatch.setenv("HUGGINGFACE_API_TOKEN", "hf")
    loading = _response(503, content=b'{"error": "Model is currently loading", "estimated_time": 20}', content_type="application/json")
    with patch("src.ai.marketing.image_generation.httpx.post", return_value=loading):
        with pytest.raises(ImageGenerationError) as exc:
            generate_campaign_image("x", provider="huggingface")
    assert exc.value.status == "PROVIDER_ERROR" and "loading" in exc.value.message


# --- falling back -----------------------------------------------------

def test_a_failing_or_busy_provider_falls_back_to_the_next(monkeypatch, _clean_env):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf")
    monkeypatch.setenv("HUGGINGFACE_API_TOKEN", "hf")
    posts = [_response(429, json_body={"errors": [{"message": "daily free allocation exceeded"}]}, content_type="application/json",
                       headers={"retry-after": "3600"}),
             _response(402, content=b'{"error": "monthly credits exceeded"}', content_type="application/json")]
    with patch("src.ai.marketing.image_generation.httpx.post", side_effect=posts), \
         patch("src.ai.marketing.image_generation.httpx.get", return_value=_response(content=JPEG, content_type="image/jpeg")):
        image = generate_campaign_image("x")
    assert image.provider == "pollinations"
    assert image.attempts == [{"provider": "cloudflare", "reason": "busy"}, {"provider": "huggingface", "reason": "busy"}]
    assert _clean_env == {"cloudflare", "huggingface"}  # set aside until their Retry-After
    # Next time the busy ones are skipped without a call.
    with patch("src.ai.marketing.image_generation.httpx.post") as post, \
         patch("src.ai.marketing.image_generation.httpx.get", return_value=_response(content=JPEG, content_type="image/jpeg")):
        assert generate_campaign_image("x").provider == "pollinations"
    post.assert_not_called()


def test_every_provider_failing_is_one_honest_error(monkeypatch):
    monkeypatch.setenv("HUGGINGFACE_API_TOKEN", "hf")
    with patch("src.ai.marketing.image_generation.httpx.post", side_effect=httpx.ConnectError("down")), \
         patch("src.ai.marketing.image_generation.httpx.get", side_effect=httpx.ConnectError("down")):
        with pytest.raises(ImageGenerationError) as exc:
            generate_campaign_image("x")
    assert exc.value.status == "PROVIDER_ERROR"
    assert exc.value.attempts == [{"provider": "huggingface", "reason": "failed"}, {"provider": "pollinations", "reason": "failed"}]


# --- capability -------------------------------------------------------

def test_capability_names_the_providers_and_that_text_leaves_keel(monkeypatch):
    capability = get_image_generation_capability()
    assert capability == {"available": True, "provider": "pollinations", "providers": ["pollinations"], "external": True, "reason": None}
    monkeypatch.setenv("MARKETING_IMAGE_PROVIDERS", "huggingface")  # listed but no token: not usable
    assert get_image_generation_capability()["available"] is False
