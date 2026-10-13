"""
AI analysis of competitors and of the market, built only on evidence KEEL
has collected, with every point citing it.

The model receives a numbered list of facts - the company's own profile
and prices, what each competitor's website says (products, prices, offers,
messaging), its public listings (rating, reviews, distance) and news - and
must answer in JSON where every point cites the numbers it rests on. Points
that cite nothing, or numbers that don't exist, are dropped, so what is
shown can always be traced back to a source link. The result is labelled
as AI analysis (not verified fact) wherever it is shown.

Uses the plan's AI token allowance like the assistant and campaign
writing: reserved before the call, settled to the real count afterwards.
"""
import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

from src.ai.core import usage
from src.ai.market_inputs import competitor_intel, discovered_competitors, market_news
from src.ai.rag import llm_client

logger = logging.getLogger("KEEL_MARKET_DISCOVERY")
TOKEN_RESERVATION = 3500
MAX_TOKENS = 1400
_LANGUAGES = {"en": "English", "ar": "Arabic"}

_COMPETITOR_PROMPT = """You are a market analyst inside KEEL, a business intelligence platform for small businesses.
You analyse ONE competitor of the user's company using ONLY the numbered evidence in the user message.
Rules:
- Every point must cite the evidence numbers it is based on, e.g. "evidence": [2, 5]. A point you cannot support with evidence must not be written.
- Never invent prices, products, customer numbers, ratings or facts that are not in the evidence.
- If the evidence is too thin for a section, return an empty list for it.
- Be specific and useful to the user's company; keep each point to one or two sentences.
- Copy business, product and place names exactly as they appear in the evidence; never translate or transliterate them.
Respond with ONLY one JSON object, no markdown:
{"positioning": {"text": "...", "evidence": [..]} or null,
 "target_audience": {"text": "...", "evidence": [..]} or null,
 "strengths": [{"text": "...", "evidence": [..]}],
 "weaknesses": [{"text": "...", "evidence": [..]}],
 "differentiators": [{"text": "...", "evidence": [..]}],
 "opportunities": [{"text": "what the user's company could do in response", "evidence": [..]}]}"""

_MARKET_PROMPT = """You are a market analyst inside KEEL, a business intelligence platform for small businesses.
Summarise the market trends and developments relevant to the user's company using ONLY the numbered evidence (news articles and competitor facts).
Rules: every trend must cite evidence numbers; never invent facts, figures or events; if the evidence shows no clear trend, return an empty list.
Copy business, product and place names exactly as they appear in the evidence; never translate them.
Respond with ONLY one JSON object, no markdown:
{"trends": [{"text": "...", "evidence": [..]}], "watch": [{"text": "something the company should keep an eye on", "evidence": [..]}]}"""


class AnalysisUnavailable(Exception):
    """The model couldn't be reached or returned nothing usable."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _own_profile(conn, tenant_id: str) -> List[dict]:
    with conn.cursor() as cursor:
        cursor.execute("SELECT business_name, business_type, city, country_code FROM companies WHERE tenant_id = %s;", (tenant_id,))
        name, business_type, city, country = cursor.fetchone() or (None, None, None, None)
        cursor.execute(
            """
            SELECT localized_text(product_name), current_price, currency FROM products
            WHERE tenant_id = %s AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 12;
            """,
            (tenant_id,),
        )
        products = cursor.fetchall()
    facts = [{"text": f"The user's company: {name or 'unnamed'}, {business_type or 'business'} in {city or '?'}, {country or ''}".strip(", "),
              "url": None}]
    if products:
        listed = "; ".join(f"{p[0]} {p[1]} {p[2]}" for p in products if p[0])
        facts.append({"text": f"The user's company sells: {listed}", "url": None})
    return facts


def competitor_evidence(conn, tenant_id: str, competitor_id: str) -> List[dict]:
    competitor = discovered_competitors.get_competitor(conn, tenant_id, competitor_id)
    if competitor is None:
        raise LookupError(competitor_id)
    found = competitor_intel.get_intel(conn, tenant_id, competitor_id)
    evidence = _own_profile(conn, tenant_id)
    name = competitor["name"]
    listing = [f"Competitor: {name}"]
    if competitor.get("industry"):
        listing.append(f"industry {competitor['industry']}")
    if competitor.get("distance_km") is not None:
        listing.append(f"{competitor['distance_km']} km from the user's company")
    if competitor.get("rating") is not None:
        listing.append(f"rated {competitor['rating']} from {competitor.get('review_count') or 0} public reviews")
    if competitor.get("branch_count") and competitor["branch_count"] > 1:
        listing.append(f"{competitor['branch_count']} branches")
    source_url = next((s.get("url") for s in competitor.get("sources") or [] if s.get("url")), None)
    evidence.append({"text": ", ".join(listing), "url": source_url})
    for product in found["products"][:20]:
        price = f" - {product['price']} {product.get('currency') or ''}".rstrip() if product.get("price") is not None else ""
        evidence.append({"text": f"{name} lists {product['name']}{price} on its website", "url": product["source_url"]})
    for promo in found["promotions"][:6]:
        evidence.append({"text": f"{name} advertises: {promo['text']}", "url": promo["source_url"]})
    for message in found["messages"][:5]:
        evidence.append({"text": f"{name} describes itself: {message['text']}", "url": message["source_url"]})
    if found["social"]:
        evidence.append({"text": f"{name} is active on: " + ", ".join(s["url"] for s in found["social"][:6]),
                         "url": found["social"][0]["url"]})
    for article in market_news.latest(conn, tenant_id, 5, competitor_id):
        evidence.append({"text": f"News ({(article['published_at'] or '')[:10]}): {article['title']}", "url": article["url"]})
    return evidence


def market_evidence(conn, tenant_id: str) -> List[dict]:
    evidence = _own_profile(conn, tenant_id)
    for article in market_news.latest(conn, tenant_id, 25):
        evidence.append({"text": f"News ({(article['published_at'] or '')[:10]}, {article['source_domain'] or ''}): {article['title']}",
                         "url": article["url"]})
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT gc.competitor_name, ci.payload, ci.source_url FROM competitor_intel ci
            JOIN global_competitors gc ON gc.global_competitor_id = ci.global_competitor_id
            WHERE ci.tenant_id = %s AND ci.kind IN ('product', 'promotion') ORDER BY ci.confidence DESC NULLS LAST LIMIT 25;
            """,
            (tenant_id,),
        )
        for name, payload, url in cursor.fetchall():
            payload = payload or {}
            text = (f"{name} lists {payload.get('name')} at {payload.get('price')} {payload.get('currency') or ''}".strip()
                    if payload.get("name") else f"{name} advertises: {payload.get('text')}")
            evidence.append({"text": text, "url": url})
    return evidence


def _numbered(evidence: List[dict]) -> str:
    return "\n".join(f"[{i}] {item['text']}" for i, item in enumerate(evidence, start=1))


def _parse_json(text: str) -> dict:
    """The first JSON object in the answer; text after it is ignored."""
    start = (text or "").find("{")
    if start < 0:
        raise ValueError("no JSON object")
    value, _end = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(value, dict):
        raise ValueError("not a JSON object")
    return value


def _point(item, evidence: List[dict]) -> Optional[dict]:
    if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not item["text"].strip():
        return None
    cited = []
    for number in item.get("evidence") or []:
        try:
            number = int(number)
        except (TypeError, ValueError):
            continue
        if 1 <= number <= len(evidence) and number not in cited:
            cited.append(number)
    if not cited:
        return None  # an unsupported point is not shown
    return {"text": item["text"].strip()[:400],
            "citations": [{"n": n, "text": evidence[n - 1]["text"][:200], "url": evidence[n - 1]["url"]} for n in cited]}


def clean(raw: dict, evidence: List[dict], single: tuple, lists: tuple) -> dict:
    out = {}
    for key in single:
        out[key] = _point(raw.get(key), evidence)
    for key in lists:
        values = raw.get(key) if isinstance(raw.get(key), list) else []
        out[key] = [p for p in (_point(v, evidence) for v in values[:6]) if p]
    return out


def _ask(conn, tenant_id: str, system: str, evidence: List[dict], language: str, extra: str = "") -> dict:
    left = usage.remaining(conn, tenant_id, usage.RAG_ASSISTANT)
    reservation = usage.reserve(conn, tenant_id, usage.RAG_ASSISTANT,
                                TOKEN_RESERVATION if left is None else max(1, min(TOKEN_RESERVATION, left)))
    conn.commit()
    token_usage = {}
    user = f"{extra}Evidence:\n{_numbered(evidence)}\n\nWrite every text value in {_LANGUAGES.get(language, 'English')}."
    try:
        parsed = None
        for attempt in range(2):  # the model occasionally writes malformed JSON: ask once more
            call_usage = {}
            text = llm_client.chat_completion([{"role": "system", "content": system}, {"role": "user", "content": user}],
                                              temperature=0.2, max_tokens=MAX_TOKENS, usage_out=call_usage)
            token_usage["total_tokens"] = token_usage.get("total_tokens", 0) + (call_usage.get("total_tokens") or 0)
            try:
                parsed = _parse_json(text)
                break
            except ValueError:
                if attempt:
                    raise
                logger.info("analysis answer was not valid JSON; asking again")
    except llm_client.LLMNotConfiguredError as err:
        usage.release(conn, reservation)
        conn.commit()
        raise AnalysisUnavailable("not_configured") from err
    except llm_client.LLMRateLimitError as err:
        usage.release(conn, reservation)
        conn.commit()
        raise AnalysisUnavailable("busy") from err
    except (llm_client.LLMError, ValueError) as err:
        logger.warning("analysis failed for %s: %s: %s", tenant_id, type(err).__name__, str(err)[:200])
        if token_usage.get("total_tokens"):
            usage.settle(conn, reservation, token_usage["total_tokens"])
        else:
            usage.release(conn, reservation)
        conn.commit()
        raise AnalysisUnavailable("failed") from err
    usage.settle(conn, reservation, token_usage.get("total_tokens") or reservation["amount"])
    conn.commit()
    return parsed


def competitor_brief(name: str) -> str:
    # Said outright: without it the model sometimes analysed the user's own company instead.
    return (f"The competitor to analyse is: {name}. positioning, target_audience, strengths, weaknesses and "
            f"differentiators all describe {name}, not the user's company. Only opportunities describe what the "
            f"user's company could do.\n\n")


def analyse_competitor(conn, tenant_id: str, competitor_id: str, language: str = "en") -> dict:
    evidence = competitor_evidence(conn, tenant_id, competitor_id)
    if len(evidence) <= 3:
        # The company itself and a bare listing: nothing to analyse yet.
        return {"insufficient_evidence": True, "evidence_count": len(evidence), "generated_at": None}
    name = discovered_competitors.get_competitor(conn, tenant_id, competitor_id)["name"]
    raw = _ask(conn, tenant_id, _COMPETITOR_PROMPT, evidence, language, competitor_brief(name))
    result = clean(raw, evidence, ("positioning", "target_audience"), ("strengths", "weaknesses", "differentiators", "opportunities"))
    result.update({"insufficient_evidence": False, "evidence_count": len(evidence), "language": language,
                   "generated_at": datetime.now(timezone.utc).isoformat(), "is_ai_analysis": True})
    competitor_intel.save_analysis(conn, tenant_id, competitor_id, result)
    conn.commit()
    return result


def analyse_market(conn, tenant_id: str, language: str = "en") -> dict:
    evidence = market_evidence(conn, tenant_id)
    if len(evidence) <= 2:
        return {"insufficient_evidence": True, "evidence_count": len(evidence), "generated_at": None}
    raw = _ask(conn, tenant_id, _MARKET_PROMPT, evidence, language)
    result = clean(raw, evidence, (), ("trends", "watch"))
    result.update({"insufficient_evidence": False, "evidence_count": len(evidence), "language": language,
                   "generated_at": datetime.now(timezone.utc).isoformat(), "is_ai_analysis": True})
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO market_summaries (tenant_id, payload) VALUES (%s, %s)
            ON CONFLICT (tenant_id) DO UPDATE SET payload = EXCLUDED.payload, created_at = CURRENT_TIMESTAMP;
            """,
            (tenant_id, json.dumps(result)),
        )
    conn.commit()
    return result


def latest_market_summary(conn, tenant_id: str) -> Optional[dict]:
    with conn.cursor() as cursor:
        cursor.execute("SELECT payload FROM market_summaries WHERE tenant_id = %s;", (tenant_id,))
        row = cursor.fetchone()
    return row[0] if row else None
