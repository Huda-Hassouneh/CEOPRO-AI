"""
KEEL - Automated Marketing System, Content Generation (Phase 1).

Reuses the existing LLM infrastructure (src/ai/rag/llm_client.py's
chat_completion() - same Groq/local/paid backend selection, same retries,
same circuit breaker as the RAG chatbot) rather than a new model or a new
provider integration. This module owns only what's specific to marketing
copy: the prompt (a marketing system prompt, not RAG's chatbot one) and
parsing the structured JSON the model is asked to return.

Explicitly NOT built here (see the plan this feature shipped against):
- No vision/image understanding - this repo has no such model anywhere.
  A product image, if uploaded, is stored (routers/marketing.py) but never
  read by this module.
- No real customer/audience data - this schema has no demographic tables.
  audience_summary is always an LLM-generated suggestion; the prompt
  forbids presenting it as measured fact and the app labels it as an AI
  suggestion in the customer's language.
- No real A/B testing/performance optimization - this only generates
  multiple static variants; nothing here tracks real campaign performance.
"""
import json
import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from src.ai.marketing.creative_direction import THEMES
from src.ai.rag import llm_client

logger = logging.getLogger("CEOPRO_AI_MARKETING")

PLATFORMS = ("INSTAGRAM", "FACEBOOK", "TIKTOK", "GOOGLE_ADS")

STRATEGIES: Dict[str, str] = {
    "SALES_DRIVEN": "Sales-driven: focus on the product's concrete benefits and a clear reason to buy now. Direct, benefit-led language.",
    "BRAND_AWARENESS": "Brand awareness: focus on memorability and the brand's identity/values rather than an immediate sale. No hard sales push.",
    "STORYTELLING": "Storytelling: frame the product inside a short relatable narrative or scenario a customer would recognize themselves in.",
    "URGENCY": "Urgency-based: honest urgency only (e.g. seasonal relevance, limited use-case framing) - never invent a fake countdown, stock level, or discount that wasn't provided.",
    "INFLUENCER_STYLE": "Influencer-style: first-person, casual, enthusiastic tone as if a real person is genuinely recommending the product to their own audience.",
}

# Advisory style/length guidance per platform - enforced server-side only
# for GOOGLE_ADS's hard character limits (see _enforce_platform_limits());
# Instagram/Facebook/TikTok have no comparably strict hard limit worth
# truncating text against, so those are prompt guidance only.
_PLATFORM_RULES = {
    "INSTAGRAM": "Casual, visual-first tone. Strong hook in the first line. 5-15 relevant hashtags.",
    "FACEBOOK": "Slightly longer, conversational tone is fine. At most 1-3 hashtags (Facebook audiences respond poorly to hashtag-heavy copy).",
    "TIKTOK": "Very short, punchy, trend-aware, first-person energy. Hook in the first line. 3-8 casual/trend-style hashtags.",
    "GOOGLE_ADS": "Strict format: headline must be <=30 characters, body_copy (the ad description) must be <=90 characters. No hashtags - always return an empty hashtags list for this platform.",
}

_GOOGLE_ADS_HEADLINE_LIMIT = 30
_GOOGLE_ADS_BODY_LIMIT = 90

_VARIANTS_PER_PLATFORM_DEFAULT = 2
_MAX_TOKENS = 2200

_SYSTEM_PROMPT = """You are a marketing copywriter working inside KEEL, a business intelligence platform for small and medium businesses. You write ad copy for a specific product based ONLY on the information given to you in the user message - you never invent facts (fake prices, fake discounts, fake stock levels, fake statistics, fake awards, fake customer counts) that were not provided.

You must respond with ONLY a single valid JSON object, no markdown code fences, no commentary before or after it, matching exactly this shape:

{
  "audience_summary": "string",
  "creative_direction": "string",
  "image_prompt": "string",
  "platforms": {
    "<PLATFORM>": [{"headline": "string", "body_copy": "string", "hashtags": ["string", ...], "cta": "string"}, ...],
    ...one key for each platform the user message asks for, and no others
  }
}

audience_summary: a short (2-4 sentence) likely-customer-persona suggestion (interests, rough age range, purchasing context) inferred from the product itself. This is ALWAYS an AI-generated suggestion, never measured customer data - word it as a suggestion and never state demographic numbers as if they were confirmed facts. Do not start it with a label or disclaimer; the app shows it under its own "AI suggestion, not measured" label in the customer's language.

creative_direction: a short (3-6 sentence) structured visual-creative brief for a FUTURE image/video generation step - combine the product information, market positioning, the chosen visual theme (or the tenant's own custom_creative_prompt when given), and the ad strategy into one coherent description of what the final ad creative should look/feel like (composition, mood, color/lighting direction, what should be visually emphasized). Describe it only - it is a brief, not a finished asset, and the app labels it as such; do not add a closing note about images or videos.

image_prompt: ALWAYS in English whatever language the rest is in - one paragraph (40-80 words) describing a single photograph-style advertising image of the product for an AI image model: the product itself as the clear subject, setting, composition, lighting, mood and colours, following the creative direction. No words, letters, logos or prices in the image; no people's faces unless the product needs them.

Each platform's list must contain exactly the number of variants requested in the user message, each meaningfully different from the others (different angle/hook), all consistent with the given strategy, style, tone, and focus. Follow each platform's own formatting rules exactly as given in the user message, especially GOOGLE_ADS's character limits.
"""


class MarketingGenerationError(Exception):
    """Raised when the LLM call fails or returns content that can't be
    parsed into the required shape after one retry - the router maps this
    to a clear error response, never a fabricated/partial campaign."""


@dataclass
class ContentVariant:
    headline: Optional[str]
    body_copy: str
    hashtags: List[str]
    cta: Optional[str]


@dataclass
class GeneratedCampaign:
    audience_summary: str
    creative_direction: str
    variants_by_platform: Dict[str, List[ContentVariant]]
    image_prompt: Optional[str] = None


def _build_user_prompt(
    product_understanding: str, style: Optional[str], tone: Optional[str], focus: Optional[str],
    strategy_type: str, positioning_label: Optional[str], variants_per_platform: int,
    creative_theme: Optional[str] = None, custom_creative_prompt: Optional[str] = None,
    platforms=PLATFORMS,
) -> str:
    lines = [
        "Product information (use only what is stated here - do not invent additional facts):",
        product_understanding.strip() or "(No product description was provided.)",
        "",
        f"Ad strategy: {STRATEGIES[strategy_type]}",
    ]
    if style:
        lines.append(f"Requested style: {style}")
    if tone:
        lines.append(f"Requested tone: {tone}")
    if focus:
        lines.append(f"Requested focus: {focus}")
    if positioning_label:
        lines.append(
            f"Market positioning (derived from this tenant's real competitor pricing data): {positioning_label}. "
            "Let this inform the price framing, but do not state specific prices unless they appear in the product information above."
        )
    else:
        lines.append("Market positioning: not available for this product - do not claim a specific price tier.")

    if creative_theme == "CUSTOM" and custom_creative_prompt:
        lines.append(f"Visual creative direction: follow this custom instruction exactly - {custom_creative_prompt}")
    elif creative_theme:
        theme_line = f"Visual creative direction theme: {THEMES[creative_theme]}"
        if custom_creative_prompt:
            theme_line += f" Additional tenant instructions to also incorporate: {custom_creative_prompt}"
        lines.append(theme_line)

    lines.append("")
    lines.append(f"Write only these platforms: {', '.join(platforms)}. "
                 f"Generate exactly {variants_per_platform} variant(s) per platform. Platform rules:")
    for platform in platforms:
        lines.append(f"- {platform}: {_PLATFORM_RULES[platform]}")

    return "\n".join(lines)


# Fixed English labels the model used to be asked to write into the text
# itself. In an Arabic campaign they appeared in English mid-text, so the
# app now shows its own translated labels instead; these remove them from
# older campaigns and from any answer that still includes them.
_AUDIENCE_LABEL = re.compile(r"^\s*likely audience\s*\(ai[- ]suggested,?\s*not measured\)\s*[:：-]?\s*", re.IGNORECASE)
_NOT_GENERATED_NOTE = re.compile(r"\s*no image or video has been generated from this brief yet\.?\s*$", re.IGNORECASE)


def without_fixed_labels(audience_summary: Optional[str], creative_direction: Optional[str]):
    if audience_summary:
        audience_summary = _AUDIENCE_LABEL.sub("", audience_summary).strip()
    if creative_direction:
        creative_direction = _NOT_GENERATED_NOTE.sub("", creative_direction).strip()
    return audience_summary, creative_direction


def _strip_code_fences(text: str) -> str:
    match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    return match.group(1) if match else text.strip()


def _enforce_platform_limits(platform: str, variant: ContentVariant) -> ContentVariant:
    if platform != "GOOGLE_ADS":
        return variant
    headline = (variant.headline or "")[:_GOOGLE_ADS_HEADLINE_LIMIT]
    body_copy = variant.body_copy[:_GOOGLE_ADS_BODY_LIMIT]
    return ContentVariant(headline=headline, body_copy=body_copy, hashtags=[], cta=variant.cta)


def _parse_response(raw_text: str, platforms=PLATFORMS) -> GeneratedCampaign:
    payload = json.loads(_strip_code_fences(raw_text))

    audience_summary = payload["audience_summary"]
    creative_direction = payload["creative_direction"]
    platforms_payload = payload["platforms"]
    missing = [p for p in platforms if p not in platforms_payload or not platforms_payload[p]]
    if missing:
        raise MarketingGenerationError(f"Model response is missing variants for: {missing}")

    variants_by_platform: Dict[str, List[ContentVariant]] = {}
    for platform in platforms:
        variants = []
        for item in platforms_payload[platform]:
            variant = ContentVariant(
                headline=item.get("headline"),
                body_copy=item["body_copy"],
                hashtags=list(item.get("hashtags") or []),
                cta=item.get("cta"),
            )
            variants.append(_enforce_platform_limits(platform, variant))
        variants_by_platform[platform] = variants

    audience_summary, creative_direction = without_fixed_labels(audience_summary, creative_direction)
    image_prompt = payload.get("image_prompt")
    return GeneratedCampaign(
        audience_summary=audience_summary, creative_direction=creative_direction,
        variants_by_platform=variants_by_platform,
        image_prompt=image_prompt.strip()[:1500] if isinstance(image_prompt, str) and image_prompt.strip() else None,
    )


_LANGUAGE_NAMES = {"en": "English", "ar": "Arabic", "fr": "French"}


def generate_campaign_content(
    product_understanding: str,
    style: Optional[str] = None,
    tone: Optional[str] = None,
    focus: Optional[str] = None,
    strategy_type: str = "SALES_DRIVEN",
    positioning_label: Optional[str] = None,
    variants_per_platform: int = _VARIANTS_PER_PLATFORM_DEFAULT,
    creative_theme: Optional[str] = None,
    custom_creative_prompt: Optional[str] = None,
    language: str = "en",
    usage_out: Optional[dict] = None,
    platforms: Optional[List[str]] = None,
) -> GeneratedCampaign:
    """
    Calls the LLM once (chat_completion() - see its own docstring for
    backend selection/retries) to generate an audience suggestion, a
    structured visual creative_direction brief, and ad-copy variants for
    every platform, all in one structured response rather than one call
    per platform/field - keeps this within the free-tier Groq rate/latency
    budget flagged as a real risk in this feature's plan.

    creative_theme (one of creative_direction.THEMES, or None) and
    custom_creative_prompt fold the tenant's visual-direction choice into
    the same prompt/response rather than a separate call - see
    _build_user_prompt()'s own handling of "CUSTOM" vs a named theme.

    Retries the LLM call exactly once if the first response can't be
    parsed into the required JSON shape (a real, occasional LLM failure
    mode distinct from the network-level retries chat_completion() already
    does) - raises MarketingGenerationError if the second attempt also
    fails, rather than ever returning a partial/guessed campaign.
    """
    if strategy_type not in STRATEGIES:
        raise ValueError(f"Unknown strategy_type: {strategy_type!r}")
    if creative_theme is not None and creative_theme not in THEMES:
        raise ValueError(f"Unknown creative_theme: {creative_theme!r}")
    # The Studio asks for one post (one caption for one image); other
    # callers still get every platform.
    platforms = tuple(p for p in PLATFORMS if p in (platforms or PLATFORMS)) or PLATFORMS

    user_prompt = _build_user_prompt(
        product_understanding, style, tone, focus, strategy_type, positioning_label, variants_per_platform,
        creative_theme, custom_creative_prompt, platforms,
    )
    if language in _LANGUAGE_NAMES and language != "en":
        user_prompt += (f"\n\nWrite every customer-facing text (audience summary, creative direction, headlines, "
                        f"captions, hashtags and calls to action) in {_LANGUAGE_NAMES[language]}. Keep the JSON keys "
                        f"and image_prompt in English.")
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    last_error = None
    for attempt in range(2):
        try:
            raw_text = llm_client.chat_completion(messages, temperature=0.7, max_tokens=_MAX_TOKENS, usage_out=usage_out)
        except llm_client.LLMError as err:
            raise MarketingGenerationError(f"LLM provider call failed: {err}") from err

        try:
            return _parse_response(raw_text, platforms)
        except (json.JSONDecodeError, KeyError, TypeError) as err:
            last_error = err
            logger.warning("Marketing content generation returned unparsable JSON (attempt %d): %s", attempt + 1, err)

    raise MarketingGenerationError(f"Model did not return valid campaign content after retrying: {last_error}")
