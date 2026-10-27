"""The one User-Agent KEEL's market collectors identify themselves with.

Wikimedia (the "Company database" source) and many websites refuse automated
clients whose User-Agent gives no way to contact the operator, so set
MARKET_RESEARCH_CONTACT (an email address or a web page about the service);
the configuration check warns while it is missing. MARKET_RESEARCH_USER_AGENT
(or the older SCRAPER_USER_AGENT) replaces the whole string.
"""
import os

CONTACT_SETTING = "MARKET_RESEARCH_CONTACT"
PRODUCT = "KEEL-MarketResearch/1.0"
PURPOSE = "business intelligence; respects robots.txt and API terms"


def build() -> str:
    override = (os.getenv("MARKET_RESEARCH_USER_AGENT") or os.getenv("SCRAPER_USER_AGENT") or "").strip()
    if override:
        return override
    contact = (os.getenv(CONTACT_SETTING) or "").strip()
    return f"{PRODUCT} (+{contact}; {PURPOSE})" if contact else f"{PRODUCT} ({PURPOSE})"


def has_contact() -> bool:
    """A contact is set, or a replacement User-Agent that carries one (an email address or a web address)."""
    if (os.getenv(CONTACT_SETTING) or "").strip():
        return True
    agent = build()
    return "@" in agent or "http://" in agent or "https://" in agent


USER_AGENT = build()
