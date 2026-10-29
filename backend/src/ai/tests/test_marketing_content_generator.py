"""
Unit tests for src/ai/marketing/content_generator.py - the LLM call is
mocked at llm_client.chat_completion (the same reusable provider-selection
function rag/llm_client.py's own tests exercise directly), so these only
cover this module's own prompt-building, JSON parsing, retry-on-malformed-
response, and platform-limit enforcement.
"""
import json
from unittest.mock import patch

import pytest

from src.ai.marketing import content_generator as cg


@pytest.fixture(autouse=True)
def _isolated_factual_review(monkeypatch):
    """These parser/provider-contract tests isolate the separate factual auditor.

    Its fail-closed behavior is exercised in test_phase3_ai_correctness.py.
    """
    monkeypatch.setattr(cg, '_check_grounding', lambda *a: None)


def _valid_response_json(**overrides):
    base = {
        "audience_summary": "Likely audience (AI-suggested, not measured): busy professionals.",
        "creative_direction": "A clean, minimal product shot on a plain desk background. No image or video has been generated from this brief yet.",
        "platforms": {
            "INSTAGRAM": [{"headline": "H1", "body_copy": "B1", "hashtags": ["#a"], "cta": "Shop now"}],
            "FACEBOOK": [{"headline": "H2", "body_copy": "B2", "hashtags": ["#b"], "cta": "Learn more"}],
            "TIKTOK": [{"headline": "H3", "body_copy": "B3", "hashtags": ["#c"], "cta": "Watch now"}],
            "GOOGLE_ADS": [{"headline": "A very long headline that exceeds thirty characters", "body_copy": "A very long ad description that definitely exceeds the ninety character Google Ads limit by quite a lot.", "hashtags": ["#should-be-dropped"], "cta": "Buy"}],
        },
    }
    base.update(overrides)
    return json.dumps(base)


def scripted_campaign_completion(messages, *, campaign_json=None, total_tokens=100, **kwargs):
    """Explicit offline provider fixture for both generation and factual review.

    The synthetic H1/B1 copy contains no product facts. Return the review
    contract for that separate call; keep the real parser/grounding checks.
    """
    if messages[0]["content"] == cg._GROUNDING_PROMPT:
        text = json.dumps({"supported": True, "unsupported_claims": [], "claims": []})
    else:
        text = campaign_json or _valid_response_json()
    return text, {"total_tokens": total_tokens}


def test_generate_campaign_content_parses_valid_response_and_enforces_google_ads_limits():
    with patch("src.ai.marketing.content_generator.llm_client.chat_completion", return_value=_valid_response_json()) as mock_call:
        result = cg.generate_campaign_content("A tidy desk widget.", strategy_type="SALES_DRIVEN")

    # The fixed English label is the app's job (translated), never part of the text.
    assert result.audience_summary == "busy professionals."
    assert set(result.variants_by_platform.keys()) == set(cg.PLATFORMS)

    google_variant = result.variants_by_platform["GOOGLE_ADS"][0]
    assert len(google_variant.headline) <= cg._GOOGLE_ADS_HEADLINE_LIMIT
    assert len(google_variant.body_copy) <= cg._GOOGLE_ADS_BODY_LIMIT
    assert google_variant.hashtags == []  # Google Ads never carries hashtags, even if the model returned some.

    ig_variant = result.variants_by_platform["INSTAGRAM"][0]
    assert ig_variant.headline == "H1"
    assert ig_variant.hashtags == ["#a"]

    mock_call.assert_called_once()
    sent_messages = mock_call.call_args.args[0]
    assert sent_messages[0]["role"] == "system"
    assert "A tidy desk widget." in sent_messages[1]["content"]


def test_generate_campaign_content_strips_markdown_code_fences():
    fenced = f"```json\n{_valid_response_json()}\n```"
    with patch("src.ai.marketing.content_generator.llm_client.chat_completion", return_value=fenced):
        result = cg.generate_campaign_content("A tidy desk widget.")
    assert set(result.variants_by_platform.keys()) == set(cg.PLATFORMS)


def test_generate_campaign_content_retries_once_on_malformed_json_then_succeeds():
    responses = iter(["not json at all", _valid_response_json()])
    with patch("src.ai.marketing.content_generator.llm_client.chat_completion", side_effect=lambda *a, **k: next(responses)) as mock_call:
        result = cg.generate_campaign_content("A tidy desk widget.")

    assert mock_call.call_count == 2
    assert set(result.variants_by_platform.keys()) == set(cg.PLATFORMS)


def test_generate_campaign_content_raises_after_two_malformed_responses():
    with patch("src.ai.marketing.content_generator.llm_client.chat_completion", return_value="still not json"):
        with pytest.raises(cg.MarketingGenerationError):
            cg.generate_campaign_content("A tidy desk widget.")


def test_generate_campaign_content_raises_when_a_platform_is_missing():
    incomplete = _valid_response_json(platforms={
        "INSTAGRAM": [{"headline": "H1", "body_copy": "B1", "hashtags": [], "cta": "Go"}],
        "FACEBOOK": [], "TIKTOK": [], "GOOGLE_ADS": [],
    })
    with patch("src.ai.marketing.content_generator.llm_client.chat_completion", return_value=incomplete):
        with pytest.raises(cg.MarketingGenerationError):
            cg.generate_campaign_content("A tidy desk widget.")


def test_generate_campaign_content_wraps_llm_provider_errors():
    with patch("src.ai.marketing.content_generator.llm_client.chat_completion", side_effect=cg.llm_client.LLMError("provider down")):
        with pytest.raises(cg.MarketingGenerationError):
            cg.generate_campaign_content("A tidy desk widget.")


def test_generate_campaign_content_rejects_unknown_strategy():
    with pytest.raises(ValueError):
        cg.generate_campaign_content("A tidy desk widget.", strategy_type="NOT_REAL")


def test_generate_campaign_content_rejects_unknown_theme():
    with pytest.raises(ValueError):
        cg.generate_campaign_content("A tidy desk widget.", creative_theme="NOT_REAL")


def test_generate_campaign_content_returns_creative_direction():
    with patch("src.ai.marketing.content_generator.llm_client.chat_completion", return_value=_valid_response_json()):
        result = cg.generate_campaign_content("A tidy desk widget.", creative_theme="MODERN_TECH")
    assert result.creative_direction == "A clean, minimal product shot on a plain desk background."


def test_build_user_prompt_includes_positioning_when_available():
    prompt = cg._build_user_prompt("A widget.", "bold", "friendly", "value", "URGENCY", "PREMIUM", 2)
    assert "PREMIUM" in prompt
    assert "do not state specific prices" in prompt


def test_build_user_prompt_is_honest_when_positioning_unavailable():
    prompt = cg._build_user_prompt("A widget.", None, None, None, "URGENCY", None, 2)
    assert "not available" in prompt


def test_build_user_prompt_includes_named_theme():
    prompt = cg._build_user_prompt("A widget.", None, None, None, "URGENCY", None, 2, creative_theme="LUXURY_PREMIUM")
    assert "Luxury / Premium" in prompt


def test_build_user_prompt_custom_theme_uses_prompt_instead_of_theme_description():
    prompt = cg._build_user_prompt(
        "A widget.", None, None, None, "URGENCY", None, 2,
        creative_theme="CUSTOM", custom_creative_prompt="Neon cyberpunk alley at night.",
    )
    assert "Neon cyberpunk alley at night." in prompt
    assert "follow this custom instruction exactly" in prompt


def test_build_user_prompt_named_theme_plus_custom_instructions():
    prompt = cg._build_user_prompt(
        "A widget.", None, None, None, "URGENCY", None, 2,
        creative_theme="MODERN_TECH", custom_creative_prompt="Include a blue accent color.",
    )
    assert "Modern / Tech" in prompt
    assert "Include a blue accent color." in prompt


def test_an_arabic_campaign_carries_no_english_labels():
    arabic = _valid_response_json(
        audience_summary="Likely audience (AI-suggested, not measured): العائلات التي تبحث عن حلويات رمضان.",
        creative_direction="لقطة دافئة للكنافة على طاولة إفطار. No image or video has been generated from this brief yet.",
    )
    with patch("src.ai.marketing.content_generator.llm_client.chat_completion", return_value=arabic) as mock_call:
        result = cg.generate_campaign_content("Product name: Kunafa", language="ar")
    assert result.audience_summary == "العائلات التي تبحث عن حلويات رمضان."
    assert result.creative_direction == "لقطة دافئة للكنافة على طاولة إفطار."
    system_prompt = mock_call.call_args.args[0][0]["content"]
    assert "Likely audience (AI-suggested" not in system_prompt
    assert "No image or video has been generated" not in system_prompt


def test_labels_are_removed_from_campaigns_saved_before_the_change():
    audience, direction = cg.without_fixed_labels(
        "likely audience (AI-suggested, not measured):  Busy parents.",
        "Warm kitchen light. No image or video has been generated from this brief yet.",
    )
    assert (audience, direction) == ("Busy parents.", "Warm kitchen light.")
    assert cg.without_fixed_labels(None, "") == (None, "")


def test_the_studio_gets_one_caption_for_one_post():
    one_post = json.dumps({
        "audience_summary": "a", "creative_direction": "b", "image_prompt": "A tray of kunafa",
        "platforms": {"INSTAGRAM": [{"headline": "h", "body_copy": "Fresh kunafa today", "hashtags": ["#kunafa"], "cta": "Visit"}]},
    })
    with patch("src.ai.marketing.content_generator.llm_client.chat_completion", return_value=one_post) as mock_call:
        result = cg.generate_campaign_content("Kunafa", variants_per_platform=1, platforms=["INSTAGRAM"])
    prompt = mock_call.call_args[0][0][1]["content"]
    assert "Write only these platforms: INSTAGRAM." in prompt and "GOOGLE_ADS" not in prompt
    assert list(result.variants_by_platform) == ["INSTAGRAM"]
    assert [v.body_copy for v in result.variants_by_platform["INSTAGRAM"]] == ["Fresh kunafa today"]
