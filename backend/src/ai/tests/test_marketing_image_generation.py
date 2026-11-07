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
import logging
import urllib.parse
from urllib.parse import quote
from unittest.mock import MagicMock, patch

import httpx
import pytest
from PIL import Image, ImageDraw

from src.ai.marketing import image_generation
from src.ai.marketing.image_generation import (
    GeneratedImage, ImageGenerationError, build_image_prompt,
    generate_campaign_image, get_image_generation_capability, provider_chain,
)


def _drawn(width, height, colour=(200, 120, 40)):
    """A picture with something in it (a "product" in the middle): a flat
    single-colour image is what safety filters return and is rejected."""
    picture = Image.new("RGB", (width, height), colour)
    ImageDraw.Draw(picture).ellipse((width // 4, height // 4, width * 3 // 4, height * 3 // 4), fill=(245, 245, 235))
    return picture


def _picture(size=1024, fmt="PNG"):
    buffer = io.BytesIO()
    _drawn(size, size).save(buffer, format=fmt)
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
                 "TOGETHER_API_KEYS", "POLLINATIONS_API_KEYS", "HORDE_API_KEYS", "GEMINI_API_KEYS",
                 "LOCAL_IMAGE_BASE_URL", "LOCAL_IMAGE_API", "LOCAL_IMAGE_MODEL", "LOCAL_IMAGE_API_KEY"):
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
    assert post.call_args.kwargs["json"] == {"prompt": image_generation.shape_prompt("kunafa on a tray", "SQUARE"), "steps": 4}
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
    assert get.call_args.args[0].endswith("/" + quote(image_generation.shape_prompt("kunafa & tea", "SQUARE")))
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
    # Speed history left in Redis by earlier tests must not reorder the scripted providers.
    monkeypatch.setenv("MARKETING_IMAGE_FASTEST_FIRST", "false")
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


def test_aihorde_size_can_be_reduced_without_changing_other_providers():
    assert image_generation._horde_size((1024, 1024), max_pixels=512 * 512) == (512, 512)


def test_aihorde_retries_once_at_512_after_kudos_upfront():
    rejected = _response(
        403, content_type="application/json",
        json_body={"rc": "KudosUpfront", "message": "This request requires more kudos."},
    )
    accepted = _response(json_body={"id": "job-512"}, content_type="application/json")

    def get(url, **_kwargs):
        if "/generate/check/" in url:
            return _response(json_body={"done": True}, content_type="application/json")
        if "/generate/status/" in url:
            return _response(
                json_body={"generations": [{"img": "https://r2.example/image.webp"}]},
                content_type="application/json",
            )
        return _response(content=_picture(512), content_type="image/png")

    with patch("src.ai.marketing.image_generation.httpx.post", side_effect=[rejected, accepted]) as post, \
         patch("src.ai.marketing.image_generation.httpx.get", side_effect=get), \
         patch("src.ai.marketing.image_generation.httpx.delete"), \
         patch("src.ai.marketing.image_generation.time.sleep"):
        image = image_generation._generate_via_aihorde(
            "campaign prompt", credential="registered-horde-key", size=(1024, 1024),
        )

    assert image.provider == "aihorde"
    assert post.call_count == 2
    assert [call.kwargs["json"]["params"]["width"] for call in post.call_args_list] == [768, 512]
    assert [call.kwargs["json"]["params"]["height"] for call in post.call_args_list] == [768, 512]
    assert all(call.kwargs["headers"]["apikey"] == "registered-horde-key" for call in post.call_args_list)


def test_aihorde_kudos_upfront_after_reduced_attempt_is_not_retryable():
    rejected = _response(
        403, content_type="application/json",
        json_body={"rc": "KudosUpfront", "message": "This request requires more kudos."},
    )
    with patch("src.ai.marketing.image_generation.httpx.post", side_effect=[rejected, rejected]) as post:
        with pytest.raises(ImageGenerationError) as exc:
            image_generation._generate_via_aihorde("campaign prompt", size=(1024, 1024))

    assert exc.value.retryable is False
    assert exc.value.message == "AI Horde rejected the request (HTTP 403)."
    assert post.call_count == 2
    assert [call.kwargs["json"]["params"]["width"] for call in post.call_args_list] == [768, 512]


def test_nonretryable_horde_capacity_error_still_falls_through_to_next_provider(monkeypatch):
    monkeypatch.setenv("MARKETING_IMAGE_PROVIDERS", "aihorde,pollinations")

    def horde(*_args, **_kwargs):
        raise image_generation.HordeKudosUpfront()

    def next_provider(*_args, **_kwargs):
        return GeneratedImage(content=PNG, content_type="image/png", provider="pollinations")

    with patch.dict(image_generation._PROVIDERS, {"aihorde": horde, "pollinations": next_provider}):
        image = generate_campaign_image("campaign prompt")

    assert image.provider == "pollinations"
    assert image.attempts == [{"provider": "aihorde", "reason": "failed"}]


def test_nonretryable_horde_capacity_error_prevents_job_retry_after_fallback_fails(monkeypatch):
    monkeypatch.setenv("MARKETING_IMAGE_PROVIDERS", "aihorde,pollinations")

    def horde(*_args, **_kwargs):
        raise image_generation.HordeKudosUpfront()

    def unavailable(*_args, **_kwargs):
        raise ImageGenerationError("PROVIDER_ERROR", "Provider unavailable.")

    with patch.dict(image_generation._PROVIDERS, {"aihorde": horde, "pollinations": unavailable}):
        with pytest.raises(ImageGenerationError) as exc:
            generate_campaign_image("campaign prompt")

    assert exc.value.retryable is False


def test_aihorde_rejection_logs_sanitized_structured_error(caplog):
    credential = "registered-test-secret"
    prompt = "private campaign prompt phrase"
    request_prompt = f"{prompt} ### text, letters, watermark, logo, blurry, low quality, deformed"
    response = _response(
        403,
        content_type="application/json",
        json_body={
            "rc": "AnonForbidden",
            "message": f"Access denied; apikey={credential}; request={request_prompt}",
        },
    )
    with patch("src.ai.marketing.image_generation.httpx.post", return_value=response) as post, \
         caplog.at_level(logging.WARNING, logger="CEOPRO_AI_MARKETING_IMAGE"):
        with pytest.raises(ImageGenerationError) as exc:
            image_generation._generate_via_aihorde(prompt, credential=credential)

    assert "HTTP 403 rc=AnonForbidden" in caplog.text
    assert "Access denied" in caplog.text
    assert credential not in caplog.text
    assert prompt not in caplog.text
    assert "apikey" not in caplog.text
    assert post.call_args.kwargs["headers"]["apikey"] == credential
    assert exc.value.message == "AI Horde rejected the request (HTTP 403)."


def test_aihorde_malformed_rejection_logs_status_only(caplog):
    response = _response(
        403,
        content=b"apikey=do-not-log private campaign prompt",
        content_type="text/plain",
    )
    with patch("src.ai.marketing.image_generation.httpx.post", return_value=response), \
         caplog.at_level(logging.WARNING, logger="CEOPRO_AI_MARKETING_IMAGE"):
        with pytest.raises(ImageGenerationError):
            image_generation._generate_via_aihorde("private campaign prompt")

    assert "HTTP 403" in caplog.text
    assert "rc=" not in caplog.text
    assert "message=" not in caplog.text
    assert "do-not-log" not in caplog.text
    assert "private campaign prompt" not in caplog.text


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


# --- Gemini and multi-model accounts ----------------------------------------

def test_gemini_returns_inline_image_and_busy_on_429(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", "g1")
    body = {"candidates": [{"content": {"parts": [{"text": "ok"}, {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(PNG).decode()}}]}}]}
    assert image_generation.provider_chain()[0] == "gemini#1"
    with patch("src.ai.marketing.image_generation.httpx.post", return_value=_response(json_body=body, content_type="application/json")) as post:
        assert generate_campaign_image("x", provider="gemini#1").content == PNG
    assert post.call_args.kwargs["headers"]["x-goog-api-key"] == "g1"
    with patch("src.ai.marketing.image_generation.httpx.post", return_value=_response(429, content_type="application/json")):
        with pytest.raises(image_generation.ProviderBusy):
            image_generation._generate_via_gemini("x", credential="g1")


def test_cloudflare_tries_the_next_model_and_accepts_raw_image_bytes(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNTS", "acc:tok")
    replies = [_response(500, content_type="application/json", json_body={"errors": [{"message": "model down"}]}),
               _response(content=PNG, content_type="image/png")]
    with patch("src.ai.marketing.image_generation.httpx.post", side_effect=replies) as post:
        image = generate_campaign_image("x", provider="cloudflare#1")
    urls = [c.args[0] for c in post.call_args_list]
    assert "flux-1-schnell" in urls[0] and "stable-diffusion-xl-lightning" in urls[1] and image.content == PNG


def test_cloudflare_quota_stops_instead_of_burning_the_next_model(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNTS", "acc:tok")
    with patch("src.ai.marketing.image_generation.httpx.post", return_value=_response(429, content_type="application/json")) as post:
        with pytest.raises(image_generation.ProviderBusy):
            image_generation._generate_via_cloudflare("x", credential="acc:tok")
    assert post.call_count == 1


def test_huggingface_falls_through_to_the_second_model(monkeypatch):
    replies = [_response(503, content=b'{"error": "loading"}', content_type="application/json"), _response(content=PNG)]
    with patch("src.ai.marketing.image_generation.httpx.post", side_effect=replies) as post:
        image = image_generation._generate_via_huggingface("x", credential="tok")
    assert image.content == PNG and post.call_count == 2


# --- formats and the self-hosted server ----------------------------------

def _rect(width, height, fmt="PNG"):
    buffer = io.BytesIO()
    _drawn(width, height, (10, 20, 30)).save(buffer, format=fmt)
    return buffer.getvalue()


@pytest.mark.parametrize("image_format,expected", [
    ("SQUARE", (1024, 1024)), ("PORTRAIT", (819, 1024)), ("STORY", (576, 1024)),
    ("LANDSCAPE", (1024, 576)), ("WIDE", (1024, 536)),
])
def test_a_square_image_is_centre_cropped_to_each_format(image_format, expected):
    image = image_generation.fit_to_format(GeneratedImage(content=PNG, content_type="image/png", provider="x"), image_format)
    assert (image.width, image.height) == expected
    with Image.open(io.BytesIO(image.content)) as picture:
        assert picture.size == expected


def test_an_image_already_in_the_right_shape_is_kept_untouched():
    content = _rect(1344, 768, "JPEG")
    image = image_generation.fit_to_format(GeneratedImage(content=content, content_type="image/jpeg", provider="x"), "LANDSCAPE")
    assert image.content == content and (image.width, image.height) == (1344, 768)


def test_an_unknown_format_is_refused_before_any_provider_call(monkeypatch):
    monkeypatch.setenv("HUGGINGFACE_API_TOKEN", "hf")
    with patch("src.ai.marketing.image_generation.httpx.post") as post, pytest.raises(ImageGenerationError):
        generate_campaign_image("x", image_format="BANNER")
    post.assert_not_called()


def test_each_provider_asks_for_the_formats_size(monkeypatch):
    sent = []

    def capture(url, **kwargs):
        sent.append((url, kwargs.get("json"), kwargs.get("params")))
        return _response(content=_rect(1344, 768), content_type="image/png")

    with patch("src.ai.marketing.image_generation.httpx.post", side_effect=capture), \
         patch("src.ai.marketing.image_generation.httpx.get", side_effect=capture):
        image_generation._generate_via_huggingface("x", credential="tok", size=(1344, 768))
        image_generation._generate_via_pollinations("x", credential="pk", size=(1344, 768))
    assert sent[0][1]["parameters"] == {"width": 1344, "height": 768}
    assert (sent[1][2]["width"], sent[1][2]["height"]) == (1344, 768)


def test_gemini_asks_for_the_nearest_supported_aspect_ratio():
    encoded = base64.b64encode(PNG).decode()
    ok = _response(content_type="application/json",
                   json_body={"candidates": [{"content": {"parts": [{"inlineData": {"data": encoded, "mimeType": "image/png"}}]}}]})
    with patch("src.ai.marketing.image_generation.httpx.post", return_value=ok) as post:
        image_generation._generate_via_gemini("x", credential="g1", size=(768, 1344))
        image_generation._generate_via_gemini("x", credential="g1", size=(1344, 704))
    ratios = [c.kwargs["json"]["generationConfig"]["imageConfig"]["aspectRatio"] for c in post.call_args_list]
    assert ratios == ["9:16", "16:9"]


def test_ai_horde_sizes_are_multiples_of_64_at_about_the_same_area():
    for size in [(1024, 1024), (768, 1344), (1344, 704), (896, 1120)]:
        width, height = image_generation._horde_size(size)
        assert width % 64 == 0 and height % 64 == 0 and width * height <= 768 * 768
        assert abs(width / height - size[0] / size[1]) < 0.2


def test_local_server_is_first_in_the_default_chain_and_keeps_the_prompt_at_home(monkeypatch):
    monkeypatch.setenv("HUGGINGFACE_API_TOKEN", "hf")
    monkeypatch.setenv("LOCAL_IMAGE_BASE_URL", "http://127.0.0.1:7860/")
    assert provider_chain()[0] == "local#1"
    assert get_image_generation_capability()["external"] is True  # Hugging Face can still be used
    monkeypatch.setenv("MARKETING_IMAGE_PROVIDERS", "local")
    capability = get_image_generation_capability()
    assert capability["available"] is True and capability["external"] is False


def test_local_openai_api_request_and_answer(monkeypatch):
    monkeypatch.setenv("LOCAL_IMAGE_BASE_URL", "http://127.0.0.1:7860/")
    monkeypatch.setenv("LOCAL_IMAGE_MODEL", "sdxl-turbo")
    encoded = base64.b64encode(PNG).decode()
    with patch("src.ai.marketing.image_generation.httpx.post",
               return_value=_response(content_type="application/json", json_body={"data": [{"b64_json": encoded}]})) as post:
        image = image_generation._generate_via_local("a cake", size=(896, 1120))
    assert post.call_args.args[0] == "http://127.0.0.1:7860/v1/images/generations"
    assert post.call_args.kwargs["json"]["size"] == "896x1120" and post.call_args.kwargs["json"]["model"] == "sdxl-turbo"
    assert post.call_args.kwargs["headers"] is None  # no key configured, none sent
    assert image.content == PNG and image.provider == "local" and image.model == "sdxl-turbo"


def test_local_a1111_answer_with_a_data_url_prefix(monkeypatch):
    monkeypatch.setenv("LOCAL_IMAGE_BASE_URL", "http://gpu-box:7860")
    monkeypatch.setenv("LOCAL_IMAGE_API", "a1111")
    monkeypatch.setenv("LOCAL_IMAGE_API_KEY", "lk")
    encoded = "data:image/png;base64," + base64.b64encode(PNG).decode()
    with patch("src.ai.marketing.image_generation.httpx.post",
               return_value=_response(content_type="application/json", json_body={"images": [encoded]})) as post:
        image = image_generation._generate_via_local("a cake", size=(768, 1344))
    assert post.call_args.args[0] == "http://gpu-box:7860/sdapi/v1/txt2img"
    assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer lk"}
    assert image.content == PNG


@pytest.mark.parametrize("response,error", [
    (_response(503, content=b"busy", content_type="text/plain"), image_generation.ProviderBusy),
    (_response(200, content_type="application/json", json_body={"data": []}), ImageGenerationError),
    (_response(500, content=b"oom", content_type="text/plain"), ImageGenerationError),
])
def test_local_server_failures_are_honest(monkeypatch, response, error):
    monkeypatch.setenv("LOCAL_IMAGE_BASE_URL", "http://127.0.0.1:7860")
    with patch("src.ai.marketing.image_generation.httpx.post", return_value=response), pytest.raises(error):
        image_generation._generate_via_local("x")


def test_local_server_unreachable_or_misconfigured(monkeypatch):
    with pytest.raises(ImageGenerationError) as missing:
        image_generation._generate_via_local("x")
    assert missing.value.status == "NOT_CONFIGURED"
    monkeypatch.setenv("LOCAL_IMAGE_BASE_URL", "http://127.0.0.1:7860")
    monkeypatch.setenv("LOCAL_IMAGE_API", "comfy")
    with pytest.raises(ImageGenerationError) as wrong:
        image_generation._generate_via_local("x")
    assert wrong.value.status == "NOT_CONFIGURED"
    monkeypatch.setenv("LOCAL_IMAGE_API", "openai")
    with patch("src.ai.marketing.image_generation.httpx.post", side_effect=httpx.ConnectError("refused")), \
         pytest.raises(ImageGenerationError) as down:
        image_generation._generate_via_local("x")
    assert down.value.status == "PROVIDER_ERROR"


def test_local_server_down_falls_back_to_the_free_hosted_chain(monkeypatch):
    monkeypatch.setattr(image_generation.random, "shuffle", lambda items: None)
    monkeypatch.setenv("LOCAL_IMAGE_BASE_URL", "http://127.0.0.1:7860")
    monkeypatch.setenv("HUGGINGFACE_API_TOKEN", "hf")
    monkeypatch.setenv("MARKETING_IMAGE_KEYLESS", "false")

    def answer(url, **kwargs):
        if url.startswith("http://127.0.0.1"):
            raise httpx.ConnectError("refused")
        return _response(content=PNG)

    with patch("src.ai.marketing.image_generation.httpx.post", side_effect=answer):
        image = generate_campaign_image("x", image_format="PORTRAIT")
    assert image.provider == "huggingface" and image.attempts == [{"provider": "local#1", "reason": "failed"}]
    assert (image.width, image.height) == (819, 1024) and image.image_format == "PORTRAIT"


def test_local_server_health_is_reported_without_addresses(monkeypatch):
    monkeypatch.setenv("LOCAL_IMAGE_BASE_URLS", "http://gpu-a:7860, http://gpu-b:7860")
    healthy = _response(content_type="application/json", json_body={"ok": True, "busy": False, "device": "cpu",
                                                                     "average_seconds_per_image": 150.0})

    def get(url, timeout):
        if "gpu-b" in url:
            raise httpx.ConnectError("down")
        return healthy

    with patch("src.ai.marketing.image_generation.httpx.get", side_effect=get):
        report = image_generation.local_server_health()
    assert report[0]["ok"] is True and report[0]["average_seconds_per_image"] == 150.0
    assert report[1] == {"server": 2, "ok": False}
    assert "gpu-a" not in str(report)
    assert provider_chain()[:2] == ["local#1", "local#2"]


# --- every model x every format ---------------------------------------
# Each provider is answered the way it really answers (its documented
# response shape); some always return a square whatever is asked, so the
# answer here is a square for half of them and the requested size for the
# rest. Whatever comes back, the stored image must be the format's exact
# shape, and the provider must have been told the format and the framing.

def _answer_for(base, url, kwargs, size_requested):
    width, height = size_requested if base in ("huggingface", "together", "local", "pollinations") else (1024, 1024)
    raw = _rect(width, height)
    encoded = base64.b64encode(raw).decode()
    if base == "cloudflare":
        return _response(content_type="application/json", json_body={"result": {"image": encoded}, "success": True})
    if base == "gemini":
        return _response(content_type="application/json",
                         json_body={"candidates": [{"content": {"parts": [{"inlineData": {"data": encoded, "mimeType": "image/png"}}]}}]})
    if base in ("together", "local"):
        return _response(content_type="application/json", json_body={"data": [{"b64_json": encoded}]})
    return _response(content=raw, content_type="image/png")


_PROVIDER_ENV = {
    "cloudflare": ("CLOUDFLARE_ACCOUNTS", "acct:tok"), "huggingface": ("HUGGINGFACE_API_TOKEN", "hf"),
    "together": ("TOGETHER_API_KEYS", "tg"), "gemini": ("GEMINI_API_KEYS", "g1"),
    "pollinations": ("POLLINATIONS_API_KEYS", "pk"), "local": ("LOCAL_IMAGE_BASE_URL", "http://127.0.0.1:7860"),
}


@pytest.mark.parametrize("image_format", sorted(image_generation.IMAGE_FORMATS))
@pytest.mark.parametrize("base", sorted(_PROVIDER_ENV))
def test_every_provider_delivers_every_format_in_its_exact_shape(monkeypatch, base, image_format):
    env, value = _PROVIDER_ENV[base]
    monkeypatch.setenv(env, value)
    size = image_generation.request_size(image_format)
    prompts = []

    def answer(url, **kwargs):
        body = kwargs.get("json") or {}
        prompts.append(body.get("prompt") or body.get("inputs") or
                       ((body.get("contents") or [{}])[0].get("parts") or [{}])[0].get("text") or url)
        return _answer_for(base, url, kwargs, size)

    with patch("src.ai.marketing.image_generation.httpx.post", side_effect=answer), \
         patch("src.ai.marketing.image_generation.httpx.get", side_effect=answer), \
         patch.object(image_generation.credits, "provider_call", _no_metering):
        image = generate_campaign_image("A bottle of olive oil on a wooden table, warm light", provider=base,
                                        image_format=image_format)

    target = image_generation._ratio(image_format)
    assert image.image_format == image_format
    assert abs(image.width / image.height - target) / target <= 0.02
    with Image.open(io.BytesIO(image.content)) as picture:
        assert picture.size == (image.width, image.height)
        assert min(picture.size) >= 256
    sent = prompts[0] if base != "pollinations" else urllib.parse.unquote(prompts[0])
    assert image_generation._FORMAT_COMPOSITION[image_format] in sent
    assert "not cut off" in sent and "No text" in sent and "olive oil" in sent


class _no_metering:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return MagicMock()

    def __exit__(self, *exc):
        return False


@pytest.mark.parametrize("image_format", sorted(image_generation.IMAGE_FORMATS))
def test_the_shaped_prompt_keeps_the_format_guidance_within_every_providers_limit(image_format):
    shaped = image_generation.shape_prompt("word " * 1000, image_format)
    assert len(shaped) <= 1200
    assert shaped.startswith(image_generation._FORMAT_COMPOSITION[image_format])
    assert shaped.endswith(image_generation._NO_TEXT)


def test_the_no_text_rule_is_not_repeated_when_the_prompt_already_has_it():
    shaped = image_generation.shape_prompt("Olive oil bottle. No text in the picture.", "SQUARE")
    assert shaped.count("No text") == 1 and "olive oil" in shaped.lower()


@pytest.mark.parametrize("colour", [(0, 0, 0), (255, 255, 255), (90, 140, 200)])
def test_a_blank_single_colour_image_is_rejected(colour):
    buffer = io.BytesIO()
    Image.new("RGB", (1024, 1024), colour).save(buffer, format="PNG")
    with pytest.raises(ImageGenerationError, match="blank"):
        image_generation.verify_image(GeneratedImage(content=buffer.getvalue(), content_type="image/png", provider="x"))


def test_a_blank_image_from_one_provider_falls_through_to_the_next(monkeypatch):
    monkeypatch.setenv("MARKETING_IMAGE_PROVIDERS", "huggingface,together")
    monkeypatch.setenv("HUGGINGFACE_API_TOKEN", "hf")
    monkeypatch.setenv("TOGETHER_API_KEYS", "tg")
    black = io.BytesIO()
    Image.new("RGB", (1024, 1024), (0, 0, 0)).save(black, format="PNG")
    answers = [_response(content=black.getvalue(), content_type="image/png"),
               _response(content_type="application/json", json_body={"data": [{"b64_json": base64.b64encode(PNG).decode()}]})]
    with patch("src.ai.marketing.image_generation.httpx.post", side_effect=lambda *a, **k: answers.pop(0)), \
         patch.object(image_generation.credits, "provider_call", _no_metering):
        image = generate_campaign_image("olive oil")
    assert image.provider == "together"
    assert image.attempts == [{"provider": "huggingface", "reason": "failed"}]


def test_a_seed_reaches_every_provider_that_takes_one():
    sent = []

    def capture(url, **kwargs):
        sent.append(kwargs.get("json") or kwargs.get("params") or {})
        return _response(content_type="application/json", json_body={})

    with patch("src.ai.marketing.image_generation.httpx.post", side_effect=capture), \
         patch("src.ai.marketing.image_generation.httpx.get", side_effect=capture):
        for call in (
            lambda: image_generation._generate_via_cloudflare("x", credential="a:t", size=(1024, 1024), seed=7),
            lambda: image_generation._generate_via_huggingface("x", credential="hf", size=(1024, 1024), seed=7),
            lambda: image_generation._generate_via_together("x", credential="tg", size=(1024, 1024), seed=7),
            lambda: image_generation._generate_via_pollinations("x", credential="pk", size=(1024, 1024), seed=7),
        ):
            with pytest.raises(ImageGenerationError):
                call()
    assert sent[0]["seed"] == 7  # Cloudflare
    assert any((body.get("parameters") or {}).get("seed") == 7 for body in sent)  # Hugging Face
    assert any(body.get("seed") == 7 and body.get("model", "").startswith("black-forest-labs/FLUX.1-schnell-Free") for body in sent)  # Together
    assert sent[-1]["seed"] == 7  # Pollinations


def test_stable_diffusion_models_get_a_negative_prompt_and_flux_models_do_not():
    assert "negative_prompt" not in image_generation._hf_parameters("black-forest-labs/FLUX.1-schnell", (1024, 1024), None)
    assert "text" in image_generation._hf_parameters("stabilityai/stable-diffusion-xl-base-1.0", (1024, 1024), None)["negative_prompt"]


# --- realistic commercial photo wording, fastest provider first ----------

def test_every_shaped_prompt_asks_for_a_realistic_commercial_photo_and_an_accurate_product():
    shaped = image_generation.shape_prompt("A bottle of olive oil on a wooden table", "STORY")
    assert shaped.startswith(image_generation._FORMAT_COMPOSITION["STORY"])
    for words in ("commercial product advertising photograph", "photorealistic", "shown accurately",
                  "No unrelated objects", "distorted product", "No text"):
        assert words in shaped
    assert len(shaped) <= 1200


class _FakeRedis:
    def __init__(self):
        self.lists = {}

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    def ltrim(self, key, start, stop):
        self.lists[key] = self.lists.get(key, [])[start:stop + 1]

    def lrange(self, key, start, stop):
        return self.lists.get(key, [])[start:stop + 1]

    def get(self, key):
        return None

    def setex(self, *args):
        pass


@pytest.fixture
def fake_redis(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr("src.ai.core.redis_client.get_redis_client", lambda: fake)
    return fake


def test_provider_times_are_kept_and_their_median_is_used(fake_redis):
    for seconds in (4.0, 30.0, 5.0):
        image_generation.record_seconds("cloudflare", seconds)
    assert image_generation.measured_seconds("cloudflare") == 5.0
    assert image_generation.measured_seconds("together") is None
    for _ in range(40):
        image_generation.record_seconds("cloudflare", 1.0)
    assert len(fake_redis.lists["keel:image-provider-seconds:cloudflare"]) == image_generation._TIMINGS_KEPT


def test_fast_providers_come_first_then_unmeasured_then_slow(fake_redis, monkeypatch):
    monkeypatch.setenv("HUGGINGFACE_API_TOKENS", "h1,h2")
    monkeypatch.setenv("TOGETHER_API_KEYS", "t1")
    monkeypatch.setenv("GEMINI_API_KEYS", "g1")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNTS", "a:b")
    image_generation.record_seconds("gemini", 6.0)
    image_generation.record_seconds("together", 2.5)
    image_generation.record_seconds("huggingface", 40.0)
    chain = provider_chain()
    assert chain[:2] == ["together#1", "gemini#1"], "fastest measured first"
    assert chain[2] == "cloudflare#1", "not measured yet: after the fast ones"
    assert set(chain[3:5]) == {"huggingface#1", "huggingface#2"}, "slow ones after, both accounts kept"
    assert chain[-1] == "aihorde"
    monkeypatch.setenv("MARKETING_IMAGE_FASTEST_FIRST", "false")
    assert set(provider_chain()[:5]) == set(chain[:5])


def test_a_successful_image_records_how_long_the_provider_took(fake_redis, monkeypatch):
    monkeypatch.setenv("TOGETHER_API_KEYS", "tg")
    ok = _response(content_type="application/json", json_body={"data": [{"b64_json": base64.b64encode(PNG).decode()}]})
    with patch("src.ai.marketing.image_generation.httpx.post", return_value=ok), \
         patch.object(image_generation.credits, "provider_call", _no_metering):
        generate_campaign_image("olive oil", provider="together")
    assert image_generation.measured_seconds("together") is not None


def test_aihorde_rejection_redacts_a_partial_prompt_echo(caplog):
    """A provider that echoes only the campaign's words (not the negative
    prompt KEEL appends) must not get them into the logs either."""
    prompt = "secret launch of the new olive oil tin"
    response = _response(403, content_type="application/json",
                         json_body={"rc": "BadRequest", "message": f"Rejected prompt: {prompt}"})
    with patch("src.ai.marketing.image_generation.httpx.post", return_value=response), \
         caplog.at_level(logging.WARNING, logger="CEOPRO_AI_MARKETING_IMAGE"):
        with pytest.raises(ImageGenerationError):
            image_generation._generate_via_aihorde(prompt)
    assert prompt not in caplog.text and "[redacted prompt]" in caplog.text
