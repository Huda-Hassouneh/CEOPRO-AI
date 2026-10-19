"""
Competitor products and prices matched to the company's own products.

A competitor's website facts (intel.py) say what it sells and at what
price. This module decides which of those items are the same thing as one
of the company's products - so "Products with competitor prices", "Priced
above competitors", price changes, pricing recommendations, reports and the
assistant compare like with like - and records each match in the tables
those features read (competitor_product_mappings + competitor_prices),
pointing at the page the price came from.

A match needs:
- the names to agree: most of the informative words of the company's
  product appear in the competitor's item (Arabic letters normalised, one
  letter of transliteration tolerated - shawarma/shawerma), or one of the
  product's names in the other language (from the configured AI model,
  asked once per product) does;
- the same currency (prices in different currencies are never compared);
- a plausible price: between a fifth and five times the company's own
  price - an item far outside that range is a different size or product
  ("Mansaf family tray" vs "Mansaf plate"), and is left unmatched.

Nothing is invented: an unmatched product simply has no competitor price,
and each match keeps its score and evidence.
"""
import json
import logging
import re
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Sequence

from src.market_scraper.market_discovery import match_overrides

logger = logging.getLogger("KEEL_MARKET_DISCOVERY")
MIN_SCORE = 0.75
PRICE_RATIO = (0.2, 5.0)
_AR_DIACRITICS = re.compile(r"[ً-ٰٟـ]")
_AR_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي"})
_STOP = {"the", "and", "with", "of", "a", "an", "for", "per", "new", "special", "fresh", "our", "best", "plate", "meal",
         "box", "pack", "piece", "pcs", "pc", "kg", "g", "ml", "l", "size", "small", "medium", "large", "regular",
         "مع", "و", "في", "من", "على", "طبق", "وجبه", "علبه", "حبه", "قطعه", "كيلو", "صغير", "وسط", "كبير", "عادي"}
_ALIAS_CACHE: Dict[str, List[str]] = {}


def normalize(text: str) -> str:
    text = _AR_DIACRITICS.sub("", (text or "").lower()).translate(_AR_FOLD)
    return re.sub(r"[^\w؀-ۿ]+", " ", text).strip()


def _token(word: str) -> str:
    word = re.sub(r"^(وال|بال|فال|كال|لل|ال)", "", word) if re.search(r"[؀-ۿ]", word) else word
    return word[:-1] if len(word) > 4 and word.endswith("s") else word


def tokens(text: str) -> List[str]:
    return [t for t in (_token(w) for w in normalize(text).split()) if len(t) >= 2 and t not in _STOP and not t.isdigit()]


def _word_in(word: str, words: Sequence[str]) -> bool:
    if word in words:
        return True
    # One letter of difference in a long-enough word: shawarma / shawerma, kabsa / kabseh.
    return len(word) >= 5 and any(len(w) >= 5 and SequenceMatcher(None, word, w).ratio() >= 0.8 for w in words)


def name_score(product_name: str, item_name: str) -> float:
    """Share of the product name's informative words found in the item."""
    wanted, offered = tokens(product_name), tokens(item_name)
    if not wanted or not offered:
        return 0.0
    hits = sum(1 for w in wanted if _word_in(w, offered))
    score = hits / len(wanted)
    # An item that is mostly about something else ("Mansaf sauce jar") is a weaker match.
    extra = max(0, len(offered) - len(wanted) - 2)
    return max(0.0, score - 0.05 * extra)


def aliases(name: str, ask=None) -> List[str]:
    """The product's name in the other language (Arabic <-> English), from the
    configured AI model; cached per name. Empty when no model answers."""
    key = normalize(name)
    if key in _ALIAS_CACHE:
        return _ALIAS_CACHE[key]
    names: List[str] = []
    try:
        if ask is None:
            from src.market_scraper.market_discovery.relevance import ai_hints_enabled

            if not ai_hints_enabled():
                return []
            from src.ai.rag import llm_client
            ask = llm_client.chat_completion
        answer = ask([
            {"role": "system", "content": "You translate product and menu item names between Arabic and English as they "
                                          "are written on menus and shops in the Middle East. Answer with only a JSON list of "
                                          "1 to 3 names, e.g. [\"منسف\", \"mansaf\"]."},
            {"role": "user", "content": name},
        ], temperature=0, max_tokens=500)
        listed = json.loads(re.search(r"\[.*\]", answer, re.S).group(0))
        names = [n.strip() for n in listed if isinstance(n, str) and 1 < len(n.strip()) <= 60][:3]
    except Exception as exc:  # noqa: BLE001 - matching works without aliases
        logger.info("no aliases for %r: %s", name, type(exc).__name__)
    _ALIAS_CACHE[key] = names
    return names


def best_match(product: dict, items: List[dict], product_aliases: Sequence[str] = (), context: Optional[str] = None) -> Optional[dict]:
    """The competitor item that is this product, or None. `product`:
    {name, name_alt, price, currency}; `items`: product facts with a price."""
    names = [n for n in [product.get("name"), product.get("name_alt"), *product_aliases] if n]
    best = None
    for item in items:
        if item.get("price") is None or not item.get("currency"):
            continue
        if item["currency"] != product.get("currency"):
            continue
        # Menus name an item under its section ("Pizza" > "Margherita"): the
        # section counts as part of the item's name.
        # So does the business's own name for what it sells ("Luigi's Pizza" > "Margherita").
        texts = [item["name"]] + ([f"{item['section']} {item['name']}"] if item.get("section") else []) \
            + ([f"{context} {item['name']}"] if context else [])
        score = max(name_score(n, text) for n in names for text in texts)
        if score < MIN_SCORE:
            continue
        own = product.get("price")
        if own:
            ratio = float(item["price"]) / float(own)
            if not PRICE_RATIO[0] <= ratio <= PRICE_RATIO[1]:
                continue
        candidate = {**item, "match_score": round(score, 2)}
        if best is None or (score, item.get("confidence") or 0) > (best["match_score"], best.get("confidence") or 0):
            best = candidate
    return best


# --- persistence ------------------------------------------------------------

def company_products(conn, tenant_id: str) -> List[dict]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT product_id, product_name->>'en', product_name->>'ar', localized_text(product_name), current_price, currency
            FROM products WHERE tenant_id = %s AND deleted_at IS NULL;
            """,
            (tenant_id,),
        )
        rows = cursor.fetchall()
    out = []
    for product_id, en, ar, any_name, price, currency in rows:
        name = en or any_name or ar
        out.append({"product_id": str(product_id), "name": name, "name_alt": ar if ar and ar != name else None,
                    "price": float(price) if price is not None else None, "currency": currency})
    return out


def competitor_items(conn, tenant_id: str, competitor_id: str) -> List[dict]:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT payload, source_url, confidence, retrieved_at FROM competitor_intel "
            "WHERE tenant_id = %s AND global_competitor_id = %s AND kind = 'product' "
            # A social-post caption is weaker evidence than a price list: it never feeds price matching until the owner confirmed it.
            "AND (COALESCE(payload->>'channel', 'website') = 'website' OR COALESCE((payload->>'verified')::boolean, FALSE));",
            (tenant_id, competitor_id),
        )
        rows = cursor.fetchall()
    return [{**(payload or {}), "source_url": url, "confidence": float(conf) if conf is not None else None,
             "retrieved_at": retrieved} for payload, url, conf, retrieved in rows]


def record_matches(conn, tenant_id: str, competitor_id: str, products: List[dict], with_aliases: bool = True,
                   ask=None, update_rate: bool = True) -> dict:
    """Matches one competitor's priced items to the company's products and
    records each match (mapping + price, unless the same price was already
    recorded today). Caller commits. Returns counts and the matches.

    The owner's decisions (match_overrides) win: an item rejected for a product is never offered to it, an item the
    owner chose for a product is used as its match, and a mapping whose item was rejected is switched off.
    update_rate=False when `products` is only a subset (the owner re-matched one product)."""
    items = [i for i in competitor_items(conn, tenant_id, competitor_id) if i.get("price") is not None]
    with conn.cursor() as cursor:
        cursor.execute("SELECT competitor_name FROM global_competitors WHERE global_competitor_id = %s;", (competitor_id,))
        row = cursor.fetchone()
    context = row[0] if row else None
    out = {"items_priced": len(items), "matched": 0, "currency_mismatch": 0, "matches": []}
    if not items or not products:
        return out
    currencies = {i.get("currency") for i in items}
    rejected, chosen = match_overrides.load(conn, tenant_id, competitor_id)
    matched_products = set()
    with conn.cursor() as cursor:
        for product in products:
            pid = product["product_id"]
            forced = chosen.get(pid)
            if forced:  # the owner's choice: the item must still be on the site, in the product's currency
                found = next((dict(i, match_score=1.0, owner_chosen=True) for i in items
                              if match_overrides.item_key(i["name"]) == forced and i.get("currency") == product.get("currency")), None)
            else:
                found = None
            if found is None:
                if product.get("currency") not in currencies:
                    out["currency_mismatch"] += 1 if currencies - {None} else 0
                    continue
                candidates = [i for i in items if (pid, match_overrides.item_key(i["name"])) not in rejected]
                found = best_match(product, candidates, aliases(product["name"], ask) if with_aliases else (), context)
            if found is None:
                continue
            matched_products.add(pid)
            # A mapping now pointing at a DIFFERENT item (the owner re-matched it, or a better item turned up) must not
            # keep the price series of the old item: the latest price would be one of two different products' prices.
            cursor.execute(
                "SELECT mapping_id, competitor_product_sku FROM competitor_product_mappings "
                "WHERE tenant_id = %s AND global_competitor_id = %s AND product_id = %s;", (tenant_id, competitor_id, pid))
            existing = cursor.fetchone()
            if existing and existing[1] and match_overrides.item_key(existing[1]) != match_overrides.item_key(found["name"]):
                cursor.execute("DELETE FROM competitor_prices WHERE tenant_id = %s AND mapping_id = %s;", (tenant_id, existing[0]))
            cursor.execute(
                """
                INSERT INTO competitor_product_mappings (tenant_id, global_competitor_id, product_id, competitor_product_url,
                                                         competitor_product_sku)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, global_competitor_id, product_id) DO UPDATE
                    SET is_active = TRUE, competitor_product_url = EXCLUDED.competitor_product_url,
                        competitor_product_sku = EXCLUDED.competitor_product_sku
                RETURNING mapping_id;
                """,
                (tenant_id, competitor_id, product["product_id"], found.get("source_url"), found["name"][:100]),
            )
            mapping_id = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO competitor_prices (tenant_id, mapping_id, scraped_price, currency, is_available, observed_at,
                                               source_status, is_exact_data)
                SELECT %s, %s, %s, %s, TRUE, COALESCE(%s, CURRENT_TIMESTAMP), 'ALLOWED', %s
                WHERE NOT EXISTS (
                    SELECT 1 FROM competitor_prices cp WHERE cp.tenant_id = %s AND cp.mapping_id = %s
                      AND cp.scraped_price = %s AND cp.observed_at > CURRENT_TIMESTAMP - INTERVAL '1 day');
                """,
                (tenant_id, mapping_id, found["price"], found["currency"], found.get("retrieved_at"),
                 not found.get("currency_inferred"), tenant_id, mapping_id, found["price"]),
            )
            out["matched"] += 1
            out["matches"].append({"product_id": product["product_id"], "product": product["name"], "item": found["name"],
                                   "price": found["price"], "currency": found["currency"], "score": found["match_score"], "owner_chosen": bool(found.get("owner_chosen")),
                                   "source_url": found.get("source_url")})
        if rejected:  # a mapping whose item the owner rejected stays off unless another item matched this pass
            cursor.execute(
                "SELECT product_id, competitor_product_sku FROM competitor_product_mappings "
                "WHERE tenant_id = %s AND global_competitor_id = %s AND is_active = TRUE;", (tenant_id, competitor_id))
            for pid, sku in cursor.fetchall():
                if str(pid) not in matched_products and (str(pid), match_overrides.item_key(sku or "")) in rejected:
                    cursor.execute(
                        "UPDATE competitor_product_mappings SET is_active = FALSE WHERE tenant_id = %s AND global_competitor_id = %s AND product_id = %s;",
                        (tenant_id, competitor_id, pid))
        if products and update_rate:
            cursor.execute(
                "UPDATE tenant_competitors SET product_match_rate = %s WHERE tenant_id = %s AND global_competitor_id = %s;",
                (round(out["matched"] / len(products), 4), tenant_id, competitor_id),
            )
    return out
