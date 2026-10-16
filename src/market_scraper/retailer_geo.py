"""
CEOPRO AI - Seeded-retailer geography.

Kept separate from direct_search.py so discovery.py (which direct_search.py
imports) can use it without a circular import.
"""
import os
from typing import Optional

# Where each seeded retailer is based. Without this the seeded lists were
# silently US-only for every tenant: a Jordan shop would be handed US
# retailers as "competitors". A domain is only used for a tenant that
# operates in its origin country, UNLESS an operator has verified it ships
# to that tenant's market and listed it in RETAILER_INTERNATIONAL_DOMAINS
# (comma-separated env var) - shipping cannot be inferred from a domain, so
# nothing is assumed international by default. Domains not listed here have
# unknown origin and are kept (absence of evidence is not exclusion - the
# same rule classify_competitor() applies to an unknown country).
RETAILER_DOMAIN_ORIGIN = {
    "www.sparkfun.com": "US",
    "www.impactbattery.com": "US",
    "www.makershed.com": "US",
    "www.dfrobot.com": "CN",
}


def _international_domains() -> set:
    raw = os.getenv("RETAILER_INTERNATIONAL_DOMAINS", "")
    return {d.strip().lower() for d in raw.split(",") if d.strip()}


def known_origin_country(domain: str) -> Optional[str]:
    """Origin country of a seeded retailer, or None when unknown OR when an
    operator has marked it as serving other countries too (so it is not
    treated as out-of-region anywhere)."""
    domain = (domain or "").lower()
    if domain in _international_domains():
        return None
    return RETAILER_DOMAIN_ORIGIN.get(domain)
