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
                 "HUGGINGFACE_API_TOKENS", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNTS",
                 "TOGETHER_API_KEYS", "POLLINATIONS_API_KEYS", "HORDE_API_KEYS"):
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
    assert provider_chain() == ["aihorde"]  # zero setup: only the keyless AI Horde (Pollinations needs a key)
    monkeypatch.setenv("HUGGINGFACE_API_TOKEN", "hf")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf")
    chain = provider_chain()
    assert sorted(chain[:2]) == ["cloudflare#1", "huggingface#1"] and chain[2:] == ["aihorde"]
    monkeypatch.setenv("MARKETING_IMAGE_KEYLESS", "false")
    assert sorted(provider_chain()) == ["cloudflare#1", "huggingface#1"]
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
    monkeypatch.setattr(image_generation.random, "shuffle", lambda items: None)  # fixed order for the scripted replies
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf")
    monkeypatch.setenv("HUGGINGFACE_API_TOKEN", "hf")
    monkeypatch.setenv("POLLINATIONS_API_KEYS", "pk")
    posts = [_response(429, json_body={"errors": [{"message": "daily free allocation exceeded"}]}, content_type="application/json",
                       headers={"retry-after": "3600"}),
             _response(402, content=b'{"error": "monthly credits exceeded"}', content_type="application/json")]
    def horde_down(*a, **k):
        raise ImageGenerationError("PROVIDER_ERROR", "queue unavailable")

    with patch("src.ai.marketing.image_generation.httpx.post", side_effect=posts), \
         patch.dict(image_generation._PROVIDERS, {"aihorde": horde_down}), \
         patch("src.ai.marketing.image_generation.httpx.get", return_value=_response(content=JPEG, content_type="image/jpeg")):
        image = generate_campaign_image("x")
    assert image.provider == "pollinations"
    assert [(a["provider"], a["reason"]) for a in image.attempts] == [
        ("cloudflare#1", "busy"), ("huggingface#1", "busy")]
    assert _clean_env == {"cloudflare#1", "huggingface#1"}  # set aside until their Retry-After
    # Next time the busy ones are skipped without a call.
    with patch("src.ai.marketing.image_generation.httpx.post") as post, \
         patch("src.ai.marketing.image_generation.httpx.get", return_value=_response(content=JPEG, content_type="image/jpeg")), \
         patch.dict(image_generation._PROVIDERS, {"aihorde": horde_down}):
        assert generate_campaign_image("x").provider == "pollinations"
    post.assert_not_called()


def test_every_provider_failing_is_one_honest_error(monkeypatch):
    monkeypatch.setenv("HUGGINGFACE_API_TOKEN", "hf")
    monkeypatch.setenv("POLLINATIONS_API_KEYS", "pk")
    with patch("src.ai.marketing.image_generation.httpx.post", side_effect=httpx.ConnectError("down")), \
         patch("src.ai.marketing.image_generation.httpx.get", side_effect=httpx.ConnectError("down")):
        with pytest.raises(ImageGenerationError) as exc:
            generate_campaign_image("x")
    assert exc.value.status == "PROVIDER_ERROR"
    names = [a["provider"] for a in exc.value.attempts]
    assert sorted(names[:2]) == ["huggingface#1", "pollinations#1"] and names[2:] == ["aihorde"]
    assert all(a["reason"] == "failed" for a in exc.value.attempts)


# --- capability -------------------------------------------------------

def test_capability_names_the_providers_and_that_text_leaves_keel(monkeypatch):
    capability = get_image_generation_capability()
    # Provider names are never exposed - only that an outside service is used.
    assert capability == {"available": True, "provider": "ai", "providers": ["ai"], "external": True, "reason": None}
    monkeypatch.setenv("MARKETING_IMAGE_PROVIDERS", "huggingface")  # listed but no token: not usable
    assert get_image_generation_capability()["available"] is False


# --- more free accounts, more providers, hidden names ----------------------

def test_every_extra_account_is_its_own_chain_entry(monkeypatch):
    monkeypatch.setenv("HUGGINGFACE_API_TOKENS", "a, b ,c")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNTS", "acc1:t1,acc2:t2")
    monkeypatch.setenv("TOGETHER_API_KEYS", "k1")
    chain = provider_chain()
    assert sorted(chain[:6]) == sorted(["huggingface#1", "huggingface#2", "huggingface#3", "cloudflare#1", "cloudflare#2", "together#1"])
    assert chain[6:] == ["aihorde"]


def test_rotation_spreads_load_across_accounts(monkeypatch):
    monkeypatch.setenv("HUGGINGFACE_API_TOKENS", "a,b,c")
    first = {provider_chain()[0] for _ in range(60)}
    assert first == {"huggingface#1", "huggingface#2", "huggingface#3"}


def test_each_account_uses_its_own_credential_and_cools_down_alone(monkeypatch, _clean_env):
    monkeypatch.setenv("HUGGINGFACE_API_TOKENS", "tok1,tok2")
    monkeypatch.setenv("MARKETING_IMAGE_PROVIDERS", "huggingface#1,huggingface#2")
    seen = []

    def post(url, headers=None, **kw):
        seen.append(headers["Authorization"])
        return _response(402, content=b"{}", content_type="application/json") if len(seen) == 1 else _response(content=PNG)

    with patch("src.ai.marketing.image_generation.httpx.post", side_effect=post):
        image = generate_campaign_image("x")
    assert seen == ["Bearer tok1", "Bearer tok2"] and _clean_env == {"huggingface#1"}
    assert image.provider == "huggingface"


def test_cloudflare_account_pairs(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNTS", "acc9:tok9")
    encoded = base64.b64encode(JPEG).decode()
    with patch("src.ai.marketing.image_generation.httpx.post",
               return_value=_response(json_body={"result": {"image": encoded}}, content_type="application/json")) as post:
        generate_campaign_image("x", provider="cloudflare#1")
    assert "/accounts/acc9/" in post.call_args.args[0] and post.call_args.kwargs["headers"]["Authorization"] == "Bearer tok9"


def test_together_returns_decoded_image_and_busy_on_402(monkeypatch):
    monkeypatch.setenv("TOGETHER_API_KEYS", "tk")
    body = {"data": [{"b64_json": base64.b64encode(PNG).decode()}]}
    with patch("src.ai.marketing.image_generation.httpx.post",
               return_value=_response(json_body=body, content_type="application/json")):
        assert generate_campaign_image("x", provider="together#1").content == PNG
    with patch("src.ai.marketing.image_generation.httpx.post", return_value=_response(402, content_type="application/json")):
        with pytest.raises(image_generation.ProviderBusy):
            image_generation._generate_via_together("x", credential="tk")


def test_pollinations_402_is_busy_not_a_crash():
    with patch("src.ai.marketing.image_generation.httpx.get", return_value=_response(402, content_type="application/json")):
        with pytest.raises(image_generation.ProviderBusy):
            image_generation._generate_via_pollinations("x")


def test_aihorde_polls_downloads_and_always_cancels(monkeypatch):
    monkeypatch.setattr(image_generation.time, "sleep", lambda s: None)
    checks = iter([{"done": False}, {"done": True}])

    def get(url, **kw):
        if "/generate/check/" in url:
            return _response(json_body=next(checks), content_type="application/json")
        if "/generate/status/" in url:
            return _response(json_body={"generations": [{"img": "https://r2.example/i.png"}]}, content_type="application/json")
        return _response(content=PNG)

    with patch("src.ai.marketing.image_generation.httpx.post",
               return_value=_response(json_body={"id": "job1"}, content_type="application/json")) as post, \
         patch("src.ai.marketing.image_generation.httpx.get", side_effect=get), \
         patch("src.ai.marketing.image_generation.httpx.delete") as delete:
        image = generate_campaign_image("x", provider="aihorde")
    params = post.call_args.kwargs["json"]["params"]
    assert image.content == PNG and params["width"] % 64 == 0 and params["height"] % 64 == 0
    assert post.call_args.kwargs["headers"]["apikey"] == "0000000000"
    delete.assert_called_once()


def test_aihorde_queue_timeout_cancels_and_is_busy(monkeypatch):
    monkeypatch.setattr(image_generation, "_HORDE_MAX_WAIT", 0.0)
    with patch("src.ai.marketing.image_generation.httpx.post",
               return_value=_response(json_body={"id": "job1"}, content_type="application/json")), \
         patch("src.ai.marketing.image_generation.httpx.delete") as delete:
        with pytest.raises(image_generation.ProviderBusy):
            image_generation._generate_via_aihorde("x")
    delete.assert_called_once()


def test_keyless_pollinations_is_never_in_the_default_chain():
    # Its keyless tier stamps a visible provider watermark on every image.
    assert "pollinations" not in provider_chain() and image_generation._credentials("pollinations") == []
