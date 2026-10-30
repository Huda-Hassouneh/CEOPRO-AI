"""
Unit tests for the Automated Marketing System's endpoints
(routers/marketing.py) - same offline-unit convention as test_products.py:
DB fully mocked, content_generator/positioning/url_extractor mocked at
their call sites inside the router module, assertions on the HTTP
contract and on exactly what the endpoint hands down to its collaborators.
"""
import os
from unittest.mock import MagicMock, patch

import time

import jwt
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-unit-tests")

from src.ai.main import app  # noqa: E402
from src.ai.marketing.content_generator import ContentVariant, GeneratedCampaign, MarketingGenerationError  # noqa: E402
from src.ai.marketing.url_extractor import ExtractedProductInfo, URLExtractionError  # noqa: E402
from src.ai.marketing import image_generation as image_generation_module  # noqa: E402

client = TestClient(app)
_SECRET = os.environ["JWT_SECRET"]


def _token(tenant_id="t1", user_id="u1"):
    return jwt.encode({"tenant_id": tenant_id, "user_id": user_id, "ev": True, "exp": int(time.time()) + 3600}, _SECRET, algorithm="HS256")


def _auth():
    return {"Authorization": f"Bearer {_token()}"}


def _fake_generated_campaign():
    variant = ContentVariant(headline="Meet the Widget", body_copy="A great widget for your desk.", hashtags=["#widget"], cta="Shop now")
    return GeneratedCampaign(
        audience_summary="Likely audience (AI-suggested, not measured): office workers who like tidy desks.",
        creative_direction="A clean, minimal product shot on a plain desk background. No image or video has been generated from this brief yet.",
        variants_by_platform={
            "INSTAGRAM": [variant], "FACEBOOK": [variant], "TIKTOK": [variant], "GOOGLE_ADS": [variant],
        },
    )


def _fake_campaign_row(campaign_id="c1"):
    return {
        "campaign_id": campaign_id, "product_id": None, "campaign_brief": "Product name: Widget",
        "status": "COMPLETED", "input_source": "TEXT", "style": None, "tone": None, "focus": None,
        "strategy_type": "SALES_DRIVEN", "source_text": "A great widget.", "source_url": None,
        "source_image_key": None, "audience_summary": "Likely audience (AI-suggested, not measured): ...",
        "positioning_label": None, "error_message": None, "requested_at": "2026-01-01T00:00:00+00:00",
        "completed_at": "2026-01-01T00:00:05+00:00",
        "creative_theme": "MINIMAL_CLEAN", "theme_source": "RECOMMENDED", "custom_creative_prompt": None,
        "creative_direction": "A clean, minimal product shot. No image or video has been generated from this brief yet.",
        "content": {"INSTAGRAM": [{"variant_index": 1, "headline": "Meet the Widget", "body_copy": "...", "hashtags": ["#widget"], "cta": "Shop now"}]},
    }


# --- POST /marketing/campaigns ------------------------------------------

def test_create_campaign_requires_auth():
    response = client.post("/marketing/campaigns", json={"text": "A widget."})
    assert response.status_code == 401


def test_create_campaign_rejects_zero_sources():
    response = client.post("/marketing/campaigns", json={"style": "bold"}, headers=_auth())
    assert response.status_code == 422


def test_create_campaign_rejects_multiple_sources():
    response = client.post(
        "/marketing/campaigns", json={"text": "A widget.", "url": "https://example.com/widget"}, headers=_auth(),
    )
    assert response.status_code == 422


def test_create_campaign_rejects_unknown_strategy():
    response = client.post(
        "/marketing/campaigns", json={"text": "A widget.", "strategy_type": "VIRAL_HACKS"}, headers=_auth(),
    )
    assert response.status_code == 422


def test_create_campaign_rejects_unknown_theme():
    response = client.post(
        "/marketing/campaigns", json={"text": "A widget.", "creative_theme": "SURREALIST"}, headers=_auth(),
    )
    assert response.status_code == 422


def test_create_campaign_rejects_custom_theme_without_prompt():
    response = client.post(
        "/marketing/campaigns", json={"text": "A widget.", "creative_theme": "CUSTOM"}, headers=_auth(),
    )
    assert response.status_code == 422
    assert "CUSTOM" in response.json()["detail"]


def test_create_campaign_from_text_generates_and_saves():
    fake_conn = MagicMock()
    generated = _fake_generated_campaign()
    saved_row = _fake_campaign_row()

    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.positioning.derive_positioning_label", return_value=None) as mock_positioning, \
         patch("src.ai.routers.marketing.creative_direction.recommend_theme", return_value="MINIMAL_CLEAN") as mock_recommend, \
         patch("src.ai.routers.marketing.data_access.create_campaign", return_value="c1") as mock_create, \
         patch("src.ai.routers.marketing.content_generator.generate_campaign_content", return_value=generated) as mock_generate, \
         patch("src.ai.routers.marketing.data_access.save_campaign_result") as mock_save, \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=saved_row):
        response = client.post(
            "/marketing/campaigns",
            json={"text": "A great widget for your desk.", "style": "bold", "tone": "friendly", "strategy_type": "STORYTELLING"},
            headers=_auth(),
        )

    assert response.status_code == 200
    assert response.json() == saved_row

    mock_positioning.assert_called_once_with(fake_conn, "t1", None)
    mock_recommend.assert_called_once_with(fake_conn, "t1", None, None)  # no category (TEXT source), no positioning
    mock_create.assert_called_once()
    assert mock_create.call_args.kwargs["input_source"] == "TEXT"
    assert mock_create.call_args.kwargs["strategy_type"] == "STORYTELLING"
    assert mock_create.call_args.kwargs["creative_theme"] == "MINIMAL_CLEAN"
    assert mock_create.call_args.kwargs["theme_source"] == "RECOMMENDED"

    mock_generate.assert_called_once()
    assert mock_generate.call_args.args[0] == "A great widget for your desk."
    assert mock_generate.call_args.kwargs["strategy_type"] == "STORYTELLING"
    assert mock_generate.call_args.kwargs["positioning_label"] is None
    assert mock_generate.call_args.kwargs["creative_theme"] == "MINIMAL_CLEAN"

    mock_save.assert_called_once_with(fake_conn, "t1", "c1", None, generated)


def test_create_campaign_with_explicit_theme_skips_recommendation():
    fake_conn = MagicMock()
    generated = _fake_generated_campaign()

    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.positioning.derive_positioning_label", return_value=None), \
         patch("src.ai.routers.marketing.creative_direction.recommend_theme") as mock_recommend, \
         patch("src.ai.routers.marketing.data_access.create_campaign", return_value="c1") as mock_create, \
         patch("src.ai.routers.marketing.content_generator.generate_campaign_content", return_value=generated), \
         patch("src.ai.routers.marketing.data_access.save_campaign_result"), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=_fake_campaign_row()):
        response = client.post(
            "/marketing/campaigns", json={"text": "A widget.", "creative_theme": "LUXURY_PREMIUM"}, headers=_auth(),
        )

    assert response.status_code == 200
    mock_recommend.assert_not_called()
    assert mock_create.call_args.kwargs["creative_theme"] == "LUXURY_PREMIUM"
    assert mock_create.call_args.kwargs["theme_source"] == "USER_SELECTED"


def test_create_campaign_with_custom_theme_passes_prompt_through():
    fake_conn = MagicMock()
    generated = _fake_generated_campaign()

    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.positioning.derive_positioning_label", return_value=None), \
         patch("src.ai.routers.marketing.data_access.create_campaign", return_value="c1") as mock_create, \
         patch("src.ai.routers.marketing.content_generator.generate_campaign_content", return_value=generated) as mock_generate, \
         patch("src.ai.routers.marketing.data_access.save_campaign_result"), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=_fake_campaign_row()):
        response = client.post(
            "/marketing/campaigns",
            json={"text": "A widget.", "creative_theme": "CUSTOM", "custom_creative_prompt": "Neon cyberpunk alley at night."},
            headers=_auth(),
        )

    assert response.status_code == 200
    assert mock_create.call_args.kwargs["creative_theme"] == "CUSTOM"
    assert mock_create.call_args.kwargs["custom_creative_prompt"] == "Neon cyberpunk alley at night."
    assert mock_generate.call_args.kwargs["custom_creative_prompt"] == "Neon cyberpunk alley at night."


def test_create_campaign_from_product_id_not_found_returns_404():
    fake_conn = MagicMock()
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.get_product", return_value=None):
        response = client.post("/marketing/campaigns", json={"product_id": "p-missing"}, headers=_auth())

    assert response.status_code == 404


def test_create_campaign_from_product_id_builds_understanding_from_real_fields():
    fake_conn = MagicMock()
    fake_product = {
        "product_id": "p1", "product_name": {"en": "Widget"}, "brand": {"en": "Acme"},
        "category": {"en": "Office"}, "description": {"en": "A tidy little widget."},
        "current_price": 19.99, "cost_price": None, "currency": "JOD", "source": "MANUAL",
        "created_at": None, "updated_at": None, "inventory": None,
    }
    generated = _fake_generated_campaign()

    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.get_product", return_value=fake_product), \
         patch("src.ai.routers.marketing.positioning.derive_positioning_label", return_value="PREMIUM"), \
         patch("src.ai.routers.marketing.data_access.create_campaign", return_value="c1"), \
         patch("src.ai.routers.marketing.content_generator.generate_campaign_content", return_value=generated) as mock_generate, \
         patch("src.ai.routers.marketing.data_access.save_campaign_result"), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=_fake_campaign_row()):
        response = client.post("/marketing/campaigns", json={"product_id": "p1"}, headers=_auth())

    assert response.status_code == 200
    understanding = mock_generate.call_args.args[0]
    assert "Widget" in understanding
    assert "Acme" in understanding
    assert "19.99" in understanding
    assert mock_generate.call_args.kwargs["positioning_label"] == "PREMIUM"


def _create_and_capture_brief(body, headers=None, product=None, extracted=None):
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=MagicMock()), \
         patch("src.ai.routers.marketing.get_product", return_value=product), \
         patch("src.ai.routers.marketing.url_extractor.extract_product_info_from_url", return_value=extracted), \
         patch("src.ai.routers.marketing.positioning.derive_positioning_label", return_value=None), \
         patch("src.ai.routers.marketing.creative_direction.recommend_theme", return_value="MINIMAL_CLEAN"), \
         patch("src.ai.routers.marketing.data_access.create_campaign", return_value="c1") as mock_create, \
         patch("src.ai.routers.marketing.content_generator.generate_campaign_content", return_value=_fake_generated_campaign()), \
         patch("src.ai.routers.marketing.data_access.save_campaign_result"), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=_fake_campaign_row()):
        response = client.post("/marketing/campaigns", json=body, headers={**_auth(), **(headers or {})})
    assert response.status_code == 200
    return mock_create.call_args.kwargs["campaign_brief"]


def test_campaign_title_is_the_product_name_in_the_customers_language():
    product = {
        "product_id": "p1", "product_name": {"en": "Kunafa", "ar": "كنافة"}, "brand": None, "category": None,
        "description": None, "current_price": 3.5, "currency": "JOD",
    }
    assert _create_and_capture_brief({"product_id": "p1"}, product=product) == "Kunafa"
    assert _create_and_capture_brief({"product_id": "p1"}, {"X-App-Language": "ar"}, product=product) == "كنافة"
    # No Arabic name saved: the name the customer gave is used, never an internal label.
    product["product_name"] = {"en": "Kunafa"}
    assert _create_and_capture_brief({"product_id": "p1"}, {"X-App-Language": "ar"}, product=product) == "Kunafa"


def test_campaign_title_for_a_description_or_link_is_short_and_unlabelled():
    assert _create_and_capture_brief({"text": "\n  Fresh sourdough loaves\nbaked daily"}) == "Fresh sourdough loaves"
    long_title = _create_and_capture_brief({"text": "x" * 400})
    assert len(long_title) == 120 and long_title.endswith("…")
    extracted = ExtractedProductInfo(source_url="https://shop.example.com/w", name="Widget", description=None, price=None, image_url=None)
    assert _create_and_capture_brief({"url": "https://shop.example.com/w"}, extracted=extracted) == "Widget"
    nameless = ExtractedProductInfo(source_url="https://shop.example.com/w", name=None, description="A tidy widget.", price=None, image_url=None)
    assert _create_and_capture_brief({"url": "https://shop.example.com/w"}, extracted=nameless) == "shop.example.com"


def test_create_campaign_from_url_extraction_failure_returns_422():
    fake_conn = MagicMock()
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.url_extractor.extract_product_info_from_url", side_effect=URLExtractionError("could not fetch")):
        response = client.post("/marketing/campaigns", json={"url": "https://example.com/widget"}, headers=_auth())

    assert response.status_code == 422
    assert "could not fetch" in response.json()["detail"]


def test_create_campaign_from_url_uses_extracted_text():
    fake_conn = MagicMock()
    extracted = ExtractedProductInfo(source_url="https://example.com/widget", name="Widget", description="A tidy widget.", price="19.99 JOD", image_url=None)
    generated = _fake_generated_campaign()

    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.url_extractor.extract_product_info_from_url", return_value=extracted), \
         patch("src.ai.routers.marketing.positioning.derive_positioning_label", return_value=None), \
         patch("src.ai.routers.marketing.data_access.create_campaign", return_value="c1") as mock_create, \
         patch("src.ai.routers.marketing.content_generator.generate_campaign_content", return_value=generated) as mock_generate, \
         patch("src.ai.routers.marketing.data_access.save_campaign_result"), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=_fake_campaign_row()):
        response = client.post("/marketing/campaigns", json={"url": "https://example.com/widget"}, headers=_auth())

    assert response.status_code == 200
    assert mock_create.call_args.kwargs["input_source"] == "URL"
    assert "Widget" in mock_generate.call_args.args[0]


def test_create_campaign_generation_failure_marks_campaign_failed_and_returns_502():
    fake_conn = MagicMock()
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.positioning.derive_positioning_label", return_value=None), \
         patch("src.ai.routers.marketing.data_access.create_campaign", return_value="c1"), \
         patch("src.ai.routers.marketing.content_generator.generate_campaign_content", side_effect=MarketingGenerationError("provider down")), \
         patch("src.ai.routers.marketing.data_access.mark_campaign_failed") as mock_mark_failed, \
         patch("src.ai.routers.marketing.data_access.save_campaign_result") as mock_save:
        response = client.post("/marketing/campaigns", json={"text": "A widget."}, headers=_auth())

    assert response.status_code == 502
    # The raw provider error is logged server-side; the campaign and the
    # response carry a plain explanation instead.
    assert "provider down" not in response.json()["detail"]
    stored = mock_mark_failed.call_args.args
    assert stored[:3] == (fake_conn, "t1", "c1") and "temporarily unavailable" in stored[3]
    mock_save.assert_not_called()


# --- GET /marketing/options -----------------------------------------------

def test_marketing_options_requires_auth():
    response = client.get("/marketing/options")
    assert response.status_code == 401


def test_marketing_options_returns_strategies_and_themes():
    response = client.get("/marketing/options", headers=_auth())
    assert response.status_code == 200
    body = response.json()
    assert set(body["strategies"].keys()) == {"SALES_DRIVEN", "BRAND_AWARENESS", "STORYTELLING", "URGENCY", "INFLUENCER_STYLE"}
    assert set(body["themes"].keys()) == {
        "LUXURY_PREMIUM", "MINIMAL_CLEAN", "MODERN_TECH", "SOCIAL_TRENDY",
        "BOLD_PROMOTIONAL", "LIFESTYLE", "SEASONAL", "CUSTOM",
    }


def test_marketing_options_reports_honest_capabilities_when_unconfigured(monkeypatch):
    monkeypatch.setenv("MARKETING_IMAGE_PROVIDERS", "none")
    monkeypatch.delenv("MARKETING_BACKGROUND_REMOVAL_PROVIDER", raising=False)
    response = client.get("/marketing/options", headers=_auth())
    assert response.status_code == 200
    capabilities = response.json()["capabilities"]
    assert capabilities["image_generation"] == {"available": False, "provider": None, "providers": [], "external": False,
                                                "reason": capabilities["image_generation"]["reason"]}
    assert "not configured" in capabilities["image_generation"]["reason"].lower()
    assert capabilities["background_removal"] == {"available": False, "provider": None, "reason": capabilities["background_removal"]["reason"]}
    assert "not configured" in capabilities["background_removal"]["reason"].lower()
    assert capabilities["reference_image_generation"]["available"] is False
    assert capabilities["video_generation"]["available"] is False
    assert capabilities["video_generation"]["requirements"]


def test_marketing_options_reports_image_generation_available_when_configured(monkeypatch):
    monkeypatch.setenv("MARKETING_IMAGE_PROVIDER", "aihorde")
    response = client.get("/marketing/options", headers=_auth())
    assert response.status_code == 200
    assert response.json()["capabilities"]["image_generation"] == {"available": True, "provider": "ai", "providers": ["ai"],
                                                                   "external": True, "reason": None}


def test_marketing_options_reports_background_removal_available_when_configured(monkeypatch):
    monkeypatch.setenv("MARKETING_BACKGROUND_REMOVAL_PROVIDER", "rembg")
    monkeypatch.setattr("src.ai.marketing.background_removal._rembg_installed", lambda: True)  # opt-in extra, not in the default build
    response = client.get("/marketing/options", headers=_auth())
    assert response.status_code == 200
    assert response.json()["capabilities"]["background_removal"] == {"available": True, "provider": "rembg", "reason": None}


# --- GET /marketing/campaigns / /marketing/campaigns/{id} ---------------

def test_list_campaigns_requires_auth():
    response = client.get("/marketing/campaigns")
    assert response.status_code == 401


def test_list_campaigns_passes_pagination_through():
    fake_conn = MagicMock()
    empty = {"campaigns": [], "total": 0, "limit": 5, "offset": 10}
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.data_access.list_campaigns", return_value=empty) as mock_list:
        response = client.get("/marketing/campaigns", params={"limit": 5, "offset": 10}, headers=_auth())

    assert response.status_code == 200
    assert response.json() == empty
    mock_list.assert_called_once_with(fake_conn, "t1", limit=5, offset=10, search=None)


def test_get_campaign_not_found_returns_404():
    fake_conn = MagicMock()
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=None):
        response = client.get("/marketing/campaigns/missing", headers=_auth())
    assert response.status_code == 404


def test_get_campaign_returns_full_shape():
    fake_conn = MagicMock()
    row = _fake_campaign_row()
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=row):
        response = client.get("/marketing/campaigns/c1", headers=_auth())
    assert response.status_code == 200
    body = response.json()
    # Plus the prompt the next image starts from (editable in the Studio).
    assert body.pop("image_prompt_default") == image_generation_module.build_image_prompt(row)
    assert body == row


# --- POST /marketing/campaigns/{id}/image --------------------------------

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n" + b"0" * 20


def test_upload_campaign_image_requires_auth():
    response = client.post("/marketing/campaigns/c1/image", files={"file": ("photo.png", _PNG_MAGIC, "image/png")})
    assert response.status_code == 401


def test_upload_campaign_image_rejects_unsupported_extension():
    response = client.post(
        "/marketing/campaigns/c1/image", files={"file": ("photo.gif", b"GIF89a", "image/gif")}, headers=_auth(),
    )
    assert response.status_code == 400


def test_upload_campaign_image_rejects_content_mismatch():
    response = client.post(
        "/marketing/campaigns/c1/image", files={"file": ("photo.png", b"not a real png", "image/png")}, headers=_auth(),
    )
    assert response.status_code == 400


def test_upload_campaign_image_campaign_not_found_returns_404():
    fake_conn = MagicMock()
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=None):
        response = client.post(
            "/marketing/campaigns/missing/image", files={"file": ("photo.png", _PNG_MAGIC, "image/png")}, headers=_auth(),
        )
    assert response.status_code == 404


def test_upload_campaign_image_success_stores_key_and_is_honest_about_no_analysis():
    fake_conn = MagicMock()
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=_fake_campaign_row()), \
         patch("src.ai.routers.marketing.db.minio_client", return_value=MagicMock()), \
         patch("src.ai.routers.marketing.image_storage.upload_source_image", return_value="t1/c1/key.png") as mock_upload, \
         patch("src.ai.routers.marketing.data_access.set_source_image_key", return_value=True) as mock_set_key:
        response = client.post(
            "/marketing/campaigns/c1/image", files={"file": ("photo.png", _PNG_MAGIC, "image/png")}, headers=_auth(),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["source_image_key"] == "t1/c1/key.png"
    assert "does not yet analyze" in body["note"]
    mock_upload.assert_called_once()
    mock_set_key.assert_called_once_with(fake_conn, "t1", "c1", "t1/c1/key.png")


# --- POST /marketing/campaigns/{id}/generate-image ------------------------

def _fake_campaign_row_for_image(**overrides):
    row = _fake_campaign_row()
    row.update({
        "generated_image_key": None, "image_generation_status": None,
        "image_generation_provider": None, "image_generation_error": None, "image_generated_at": None,
        "source_image_processed_key": None, "background_removal_status": None,
        "background_removal_provider": None, "background_removal_error": None,
        "background_removal_completed_at": None, "reference_image_selection": None,
        "image_generation_used_reference": False, "image_generation_reference_note": None,
    })
    row.update(overrides)
    return row


def test_generate_image_requires_auth():
    response = client.post("/marketing/campaigns/c1/generate-image")
    assert response.status_code == 401


def test_generate_image_campaign_not_found_returns_404():
    fake_conn = MagicMock()
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=None):
        response = client.post("/marketing/campaigns/missing/generate-image", headers=_auth())
    assert response.status_code == 404


def test_generate_image_campaign_not_completed_returns_409():
    fake_conn = MagicMock()
    row = _fake_campaign_row_for_image(status="PENDING")
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=row):
        response = client.post("/marketing/campaigns/c1/generate-image", headers=_auth())
    assert response.status_code == 409


def _run_generate_with_poster_failing(monkeypatch, error_status, message):
    """Provider chain fails AND the local poster breaks: the only case left that reports an error."""
    fake_conn = MagicMock()
    row = _fake_campaign_row_for_image()
    from src.ai.marketing.image_generation import ImageGenerationError
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=row), \
         patch("src.ai.routers.marketing.image_generation.generate_campaign_image", side_effect=ImageGenerationError(error_status, message)), \
         patch("src.ai.routers.marketing.designed_poster.render_designed_poster", side_effect=RuntimeError("render bug")), \
         patch("src.ai.routers.marketing.data_access.save_image_generation_failure") as mock_fail:
        response = client.post("/marketing/campaigns/c1/generate-image", headers=_auth())
    return response, mock_fail


def test_generate_image_not_configured_and_poster_failing_is_an_honest_200(monkeypatch):
    response, mock_fail = _run_generate_with_poster_failing(
        monkeypatch, "NOT_CONFIGURED", "AI image generation is not configured for this environment.")
    assert response.status_code == 200
    body = response.json()
    assert body["image_generation_status"] == "NOT_CONFIGURED" and "not configured" in body["image_generation_error"].lower()
    assert mock_fail.call_args.kwargs["status"] == "NOT_CONFIGURED"


def test_generate_image_provider_error_and_poster_failing_is_an_honest_200(monkeypatch):
    response, mock_fail = _run_generate_with_poster_failing(monkeypatch, "PROVIDER_ERROR", "No image provider produced an image (x: busy).")
    body = response.json()
    assert response.status_code == 200 and body["image_generation_status"] == "PROVIDER_ERROR"
    mock_fail.assert_called_once()


def test_no_ai_image_falls_back_to_a_designed_poster_never_an_error():
    """Every provider failing must still give the tenant a finished image, labelled as designed."""
    fake_conn = MagicMock()
    row = _fake_campaign_row_for_image()
    from src.ai.marketing.image_generation import ImageGenerationError
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=row), \
         patch("src.ai.routers.marketing.image_generation.generate_campaign_image", side_effect=ImageGenerationError("PROVIDER_ERROR", "all busy")), \
         patch("src.ai.routers.marketing.db.minio_client", return_value=MagicMock()), \
         patch("src.ai.routers.marketing.image_storage.upload_generated_image", return_value="t1/c1/generated.png") as mock_upload, \
         patch("src.ai.routers.marketing.data_access.save_generated_image") as mock_save:
        response = client.post("/marketing/campaigns/c1/generate-image", headers=_auth())
    body = response.json()
    assert response.status_code == 200 and body["image_generation_status"] == "COMPLETED"
    assert body["image_generation_mode"] == "designed" and body["image_generation_provider"] == "designed"
    assert mock_upload.call_args.args[1][:8] == b"\x89PNG\r\n\x1a\n"   # a real PNG, not a placeholder
    assert mock_save.call_args.kwargs["provider"] == "designed"


def test_generate_image_success_stores_and_returns_completed(monkeypatch):
    monkeypatch.setenv("MARKETING_IMAGE_PROVIDER", "pollinations")
    fake_conn = MagicMock()
    row = _fake_campaign_row_for_image()
    from src.ai.marketing.image_generation import GeneratedImage
    generated = GeneratedImage(content=b"\x89PNG\r\n\x1a\nfakepng", content_type="image/png", provider="pollinations")
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=row), \
         patch("src.ai.routers.marketing.image_generation.generate_campaign_image", return_value=generated), \
         patch("src.ai.routers.marketing.db.minio_client", return_value=MagicMock()), \
         patch("src.ai.routers.marketing.image_storage.upload_generated_image", return_value="t1/c1/generated.png") as mock_upload, \
         patch("src.ai.routers.marketing.data_access.save_generated_image") as mock_save:
        response = client.post("/marketing/campaigns/c1/generate-image", headers=_auth())

    assert response.status_code == 200
    body = response.json()
    assert body["image_generation_status"] == "COMPLETED"
    assert body["image_generation_provider"] == "ai"  # the real provider is never exposed
    assert "attempts" not in str(body) and "pollinations" not in str(body)
    assert body["generated_image_key"] == "t1/c1/generated.png"
    mock_upload.assert_called_once()
    mock_save.assert_called_once_with(
        fake_conn, "t1", "c1", provider="ai", image_key="t1/c1/generated.png",
        used_reference=False, reference_note=None,
    )
    assert body["image_generation_used_reference"] is False


# --- GET /marketing/campaigns/{id}/image -----------------------------------

def test_get_campaign_image_requires_auth():
    response = client.get("/marketing/campaigns/c1/image")
    assert response.status_code == 401


def test_get_campaign_image_campaign_not_found_returns_404():
    fake_conn = MagicMock()
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=None):
        response = client.get("/marketing/campaigns/missing/image", headers=_auth())
    assert response.status_code == 404


def test_get_campaign_image_no_generated_image_returns_404():
    fake_conn = MagicMock()
    row = _fake_campaign_row_for_image()
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=row):
        response = client.get("/marketing/campaigns/c1/image", headers=_auth())
    assert response.status_code == 404


def test_get_campaign_image_generated_streams_bytes():
    fake_conn = MagicMock()
    row = _fake_campaign_row_for_image(generated_image_key="t1/c1/generated.png", image_generation_status="COMPLETED")
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=row), \
         patch("src.ai.routers.marketing.db.minio_client", return_value=MagicMock()), \
         patch("src.ai.routers.marketing.image_storage.get_image", return_value=(b"\x89PNGdata", "image/png")) as mock_get:
        response = client.get("/marketing/campaigns/c1/image", headers=_auth())

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == b"\x89PNGdata"
    mock_get.assert_called_once()


def test_get_campaign_image_source_kind_uses_source_key():
    fake_conn = MagicMock()
    row = _fake_campaign_row_for_image(source_image_key="t1/c1/source.png")
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=row), \
         patch("src.ai.routers.marketing.db.minio_client", return_value=MagicMock()), \
         patch("src.ai.routers.marketing.image_storage.get_image", return_value=(b"sourcebytes", "image/png")) as mock_get:
        response = client.get("/marketing/campaigns/c1/image", params={"kind": "source"}, headers=_auth())

    assert response.status_code == 200
    assert response.content == b"sourcebytes"
    mock_get.assert_called_once_with(mock_get.call_args.args[0], "ceopro-marketing-source-images", "t1/c1/source.png")


def test_get_campaign_image_processed_kind_uses_processed_key():
    fake_conn = MagicMock()
    row = _fake_campaign_row_for_image(source_image_processed_key="t1/c1/processed.png")
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=row), \
         patch("src.ai.routers.marketing.db.minio_client", return_value=MagicMock()), \
         patch("src.ai.routers.marketing.image_storage.get_image", return_value=(b"processedbytes", "image/png")) as mock_get:
        response = client.get("/marketing/campaigns/c1/image", params={"kind": "processed"}, headers=_auth())

    assert response.status_code == 200
    assert response.content == b"processedbytes"
    mock_get.assert_called_once_with(mock_get.call_args.args[0], "ceopro-marketing-processed-images", "t1/c1/processed.png")


def test_get_campaign_image_processed_kind_404_when_not_removed_yet():
    fake_conn = MagicMock()
    row = _fake_campaign_row_for_image()
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=row):
        response = client.get("/marketing/campaigns/c1/image", params={"kind": "processed"}, headers=_auth())
    assert response.status_code == 404


# --- POST /marketing/campaigns/{id}/remove-background ----------------------

def test_remove_background_requires_auth():
    response = client.post("/marketing/campaigns/c1/remove-background")
    assert response.status_code == 401


def test_remove_background_campaign_not_found_returns_404():
    fake_conn = MagicMock()
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=None):
        response = client.post("/marketing/campaigns/missing/remove-background", headers=_auth())
    assert response.status_code == 404


def test_remove_background_no_source_image_returns_409():
    fake_conn = MagicMock()
    row = _fake_campaign_row_for_image()  # no source_image_key
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=row):
        response = client.post("/marketing/campaigns/c1/remove-background", headers=_auth())
    assert response.status_code == 409


def test_remove_background_not_configured_by_default_is_an_honest_200(monkeypatch):
    monkeypatch.delenv("MARKETING_BACKGROUND_REMOVAL_PROVIDER", raising=False)
    fake_conn = MagicMock()
    row = _fake_campaign_row_for_image(source_image_key="t1/c1/source.png")
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=row), \
         patch("src.ai.routers.marketing.db.minio_client", return_value=MagicMock()), \
         patch("src.ai.routers.marketing.image_storage.get_image", return_value=(b"sourcebytes", "image/png")), \
         patch("src.ai.routers.marketing.data_access.save_background_removal_failure") as mock_fail:
        response = client.post("/marketing/campaigns/c1/remove-background", headers=_auth())

    assert response.status_code == 200
    body = response.json()
    assert body["background_removal_status"] == "NOT_CONFIGURED"
    assert "not configured" in body["background_removal_error"].lower()
    mock_fail.assert_called_once()
    assert mock_fail.call_args.kwargs["status"] == "NOT_CONFIGURED"


def test_remove_background_provider_error_is_an_honest_200(monkeypatch):
    monkeypatch.setenv("MARKETING_BACKGROUND_REMOVAL_PROVIDER", "rembg")
    fake_conn = MagicMock()
    row = _fake_campaign_row_for_image(source_image_key="t1/c1/source.png")
    from src.ai.marketing.background_removal import BackgroundRemovalError
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=row), \
         patch("src.ai.routers.marketing.db.minio_client", return_value=MagicMock()), \
         patch("src.ai.routers.marketing.image_storage.get_image", return_value=(b"sourcebytes", "image/png")), \
         patch("src.ai.routers.marketing.background_removal.remove_background", side_effect=BackgroundRemovalError("PROVIDER_ERROR", "Background removal failed: out of memory")), \
         patch("src.ai.routers.marketing.data_access.save_background_removal_failure") as mock_fail:
        response = client.post("/marketing/campaigns/c1/remove-background", headers=_auth())

    assert response.status_code == 200
    body = response.json()
    assert body["background_removal_status"] == "PROVIDER_ERROR"
    assert "out of memory" in body["background_removal_error"]
    mock_fail.assert_called_once()


def test_remove_background_success_stores_processed_image_and_keeps_original(monkeypatch):
    monkeypatch.setenv("MARKETING_BACKGROUND_REMOVAL_PROVIDER", "rembg")
    fake_conn = MagicMock()
    row = _fake_campaign_row_for_image(source_image_key="t1/c1/source.png")
    from src.ai.marketing.background_removal import RemovedBackgroundImage
    processed = RemovedBackgroundImage(content=b"\x89PNGprocessed", content_type="image/png", provider="rembg")
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=row), \
         patch("src.ai.routers.marketing.db.minio_client", return_value=MagicMock()), \
         patch("src.ai.routers.marketing.image_storage.get_image", return_value=(b"sourcebytes", "image/png")) as mock_get, \
         patch("src.ai.routers.marketing.background_removal.remove_background", return_value=processed), \
         patch("src.ai.routers.marketing.image_storage.upload_processed_image", return_value="t1/c1/processed.png") as mock_upload, \
         patch("src.ai.routers.marketing.data_access.save_processed_image") as mock_save, \
         patch("src.ai.routers.marketing.data_access.set_source_image_key") as mock_set_source:
        response = client.post("/marketing/campaigns/c1/remove-background", headers=_auth())

    assert response.status_code == 200
    body = response.json()
    assert body["background_removal_status"] == "COMPLETED"
    assert body["background_removal_provider"] == "rembg"
    assert body["source_image_processed_key"] == "t1/c1/processed.png"
    # The original source image is read, never overwritten/deleted.
    mock_get.assert_called_once_with(mock_get.call_args.args[0], "ceopro-marketing-source-images", "t1/c1/source.png")
    mock_set_source.assert_not_called()
    mock_upload.assert_called_once()
    mock_save.assert_called_once_with(fake_conn, "t1", "c1", provider="rembg", image_key="t1/c1/processed.png")


# --- POST /marketing/campaigns/{id}/reference-selection ---------------------

def test_reference_selection_requires_auth():
    response = client.post("/marketing/campaigns/c1/reference-selection", json={"selection": "ORIGINAL"})
    assert response.status_code == 401


def test_reference_selection_rejects_invalid_value():
    response = client.post("/marketing/campaigns/c1/reference-selection", json={"selection": "SOMETHING_ELSE"}, headers=_auth())
    assert response.status_code == 422


def test_reference_selection_campaign_not_found_returns_404():
    fake_conn = MagicMock()
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=None):
        response = client.post("/marketing/campaigns/missing/reference-selection", json={"selection": "ORIGINAL"}, headers=_auth())
    assert response.status_code == 404


def test_reference_selection_original_without_upload_returns_409():
    fake_conn = MagicMock()
    row = _fake_campaign_row_for_image()  # no source_image_key
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=row):
        response = client.post("/marketing/campaigns/c1/reference-selection", json={"selection": "ORIGINAL"}, headers=_auth())
    assert response.status_code == 409


def test_reference_selection_processed_without_background_removal_returns_409():
    fake_conn = MagicMock()
    row = _fake_campaign_row_for_image(source_image_key="t1/c1/source.png")  # no processed key
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=row):
        response = client.post("/marketing/campaigns/c1/reference-selection", json={"selection": "PROCESSED"}, headers=_auth())
    assert response.status_code == 409


def test_reference_selection_success_stores_selection():
    fake_conn = MagicMock()
    row = _fake_campaign_row_for_image(source_image_key="t1/c1/source.png")
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=row), \
         patch("src.ai.routers.marketing.data_access.set_reference_image_selection", return_value=True) as mock_set:
        response = client.post("/marketing/campaigns/c1/reference-selection", json={"selection": "ORIGINAL"}, headers=_auth())

    assert response.status_code == 200
    assert response.json() == {"campaign_id": "c1", "reference_image_selection": "ORIGINAL"}
    mock_set.assert_called_once_with(fake_conn, "t1", "c1", "ORIGINAL")


def test_reference_selection_can_be_cleared_with_null():
    fake_conn = MagicMock()
    row = _fake_campaign_row_for_image(source_image_key="t1/c1/source.png")
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=row), \
         patch("src.ai.routers.marketing.data_access.set_reference_image_selection", return_value=True) as mock_set:
        response = client.post("/marketing/campaigns/c1/reference-selection", json={"selection": None}, headers=_auth())

    assert response.status_code == 200
    mock_set.assert_called_once_with(fake_conn, "t1", "c1", None)


# --- POST /marketing/campaigns/{id}/generate-image with a reference image --

def test_generate_image_with_reference_selection_loads_and_passes_it_through(monkeypatch):
    monkeypatch.setenv("MARKETING_IMAGE_PROVIDER", "pollinations")
    fake_conn = MagicMock()
    row = _fake_campaign_row_for_image(source_image_key="t1/c1/source.png", reference_image_selection="ORIGINAL")
    from src.ai.marketing.image_generation import GeneratedImage
    generated = GeneratedImage(
        content=b"\x89PNGgenerated", content_type="image/png", provider="pollinations",
        used_reference=False, reference_note="A product reference image was provided, but this provider does not support reference-image generation - this image was generated from the text brief only, not from your uploaded photo. See MARKETING_AI_CAPABILITIES.md for why.",
    )
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=row), \
         patch("src.ai.routers.marketing.db.minio_client", return_value=MagicMock()), \
         patch("src.ai.routers.marketing.image_storage.get_image", return_value=(b"sourcebytes", "image/png")) as mock_get_image, \
         patch("src.ai.routers.marketing.image_generation.generate_campaign_image", return_value=generated) as mock_generate, \
         patch("src.ai.routers.marketing.image_storage.upload_generated_image", return_value="t1/c1/generated.png"), \
         patch("src.ai.routers.marketing.data_access.save_generated_image") as mock_save:
        response = client.post("/marketing/campaigns/c1/generate-image", headers=_auth())

    assert response.status_code == 200
    body = response.json()
    assert body["image_generation_status"] == "COMPLETED"
    # The reference image really was read from storage and threaded through...
    mock_get_image.assert_called_once_with(mock_get_image.call_args.args[0], "ceopro-marketing-source-images", "t1/c1/source.png")
    assert mock_generate.call_args.kwargs["reference_image"] == b"sourcebytes"
    # ...but the response is honest that this provider didn't actually use it.
    assert body["image_generation_used_reference"] is False
    assert "does not support reference-image generation" in body["image_generation_reference_note"]
    mock_save.assert_called_once_with(
        fake_conn, "t1", "c1", provider="ai", image_key="t1/c1/generated.png",
        used_reference=False, reference_note=generated.reference_note,
    )


def test_generate_image_without_reference_selection_passes_none():
    fake_conn = MagicMock()
    row = _fake_campaign_row_for_image()  # no reference_image_selection
    from src.ai.marketing.image_generation import GeneratedImage
    generated = GeneratedImage(content=b"\x89PNGgenerated", content_type="image/png", provider="pollinations")
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=row), \
         patch("src.ai.routers.marketing.image_generation.generate_campaign_image", return_value=generated) as mock_generate, \
         patch("src.ai.routers.marketing.db.minio_client", return_value=MagicMock()), \
         patch("src.ai.routers.marketing.image_storage.upload_generated_image", return_value="t1/c1/generated.png"), \
         patch("src.ai.routers.marketing.data_access.save_generated_image"), \
         patch("src.ai.routers.marketing.image_storage.get_image") as mock_get_image:
        response = client.post("/marketing/campaigns/c1/generate-image", headers=_auth())

    assert response.status_code == 200
    mock_get_image.assert_not_called()  # no reference selected - never touches storage for one
    assert mock_generate.call_args.kwargs["reference_image"] is None


def test_campaigns_saved_with_the_old_internal_title_read_as_the_product_name():
    from src.ai.marketing.data_access import campaign_title

    assert campaign_title("Product name: Kunafa") == "Kunafa"
    assert campaign_title("Product name: Widget (source: https://shop.example.com/w)") == "Widget"
    assert campaign_title("كنافة") == "كنافة"
    assert campaign_title(None) is None
