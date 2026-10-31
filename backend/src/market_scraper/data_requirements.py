"""
KEEL - what each kind of competitor data needs from the service operator.

One table, read by the configuration check at start-up
(src/ai/core/config_check.py, `python -m scripts.check_config`) and by the
tests that keep render.yaml, docker-compose.yml, .env.example,
docs/SECRETS.md and docs/INSTALLATION.md in step with the code
(src/market_scraper/tests/test_data_requirements.py). When a collector in
competitor_enrichment.py starts reading a new key, approval or setting, add
it here: the test fails until it is, and until it is declared everywhere a
deployment needs it.

Each need lists alternatives: any one of them being set is enough. `aliases`
are older or fallback spellings the code still reads; they need not be
declared anywhere. Names only, never values.
"""
import os
from dataclasses import dataclass
from typing import Dict, List, Tuple

KEY, APPROVAL, SETTING = "key", "approval", "setting"


@dataclass(frozen=True)
class Need:
    kind: str                  # KEY (a provider account), APPROVAL (a recorded legal/terms decision), SETTING
    names: Tuple[str, ...]     # any one of them is enough; each is declared wherever the service is deployed
    why: str
    aliases: Tuple[str, ...] = ()  # older / fallback spellings, also accepted


@dataclass(frozen=True)
class FacetRequirements:
    label: str
    needs: Tuple[Need, ...]
    optional: bool = False     # the facet still collects something without its needs (NEWS: the site's own feed)


_ACTOR = Need(SETTING, ("SCRAPER_ACTOR_USER_ID",), "the user the service records collected rows as",
              aliases=("AI_SERVICE_ACTOR_USER_ID",))

FACETS: Dict[str, FacetRequirements] = {
    "PROFILE": FacetRequirements("Business profile", (
        Need(KEY, ("GOOGLE_PLACES_API_KEY",), "Google Places, restricted to the Places API"),
    )),
    "SOCIAL_LINKS": FacetRequirements("Social profiles", ()),
    "PRICES": FacetRequirements("Prices", ()),  # read from the competitor's own website; see scripts/website_reader_check.py
    "REVIEWS": FacetRequirements("Google reviews", (
        Need(KEY, ("GOOGLE_PLACES_API_KEY",), "Google Places, restricted to the Places API"),
        Need(APPROVAL, ("PLACES_TERMS_APPROVAL_REFERENCE",), "the recorded decision to store Google reviews"),
        _ACTOR,
    )),
    "COMMENTS": FacetRequirements("Video comments", (
        Need(KEY, ("YOUTUBE_API_KEY",), "YouTube Data API v3 (free daily quota)"),
        Need(APPROVAL, ("EXTERNAL_COMMENTS_APPROVAL_REFERENCE",), "the recorded decision to store public comments"),
        _ACTOR,
    )),
    "SOCIAL_CONTENT": FacetRequirements("Social posts and comments", (
        Need(KEY, ("APIFY_API_TOKEN",), "Apify; every run is billed to the Apify account", aliases=("APIFY_TOKEN",)),
        Need(APPROVAL, ("SOCIAL_CONTENT_APPROVAL_REFERENCE",), "the recorded decision to store social-post content"),
    )),
    "NEWS": FacetRequirements("News about them", (
        Need(KEY, ("TAVILY_API_KEY", "BRAVE_SEARCH_API_KEY", "SEARXNG_INSTANCE_URL"), "a news search provider (Tavily has a free tier)"),
    ), optional=True),
    # Delivery apps and menu pictures are found through web search; Google Maps photos also use the Places key and
    # PLACES_TERMS_APPROVAL_REFERENCE (listed under REVIEWS), so without them the facet still collects the rest.
    "MARKET_MENUS": FacetRequirements("Delivery apps and menu photos", (
        Need(KEY, ("TAVILY_API_KEY", "BRAVE_SEARCH_API_KEY", "SEARXNG_INSTANCE_URL"),
             "a web search provider, to find delivery listings and menu pictures"),
    ), optional=True),
}

# Not a facet's need, but without it nobody can open Settings > Service setup to see or test the keys above.
OPERATOR_SETTING = "OPERATOR_EMAILS"
# How collectors can be contacted, in their User-Agent (user_agent.py): Wikidata and many sites refuse them without it.
CONTACT_SETTING = "MARKET_RESEARCH_CONTACT"


def _set(name: str) -> bool:
    return bool((os.getenv(name) or "").strip())


def missing(facet: str) -> List[Need]:
    """The needs of `facet` that nothing satisfies in this environment."""
    return [need for need in FACETS[facet].needs if not any(_set(name) for name in need.names + need.aliases)]


def declared_names() -> List[str]:
    """Every name a deployment must declare (aliases left out), plus OPERATOR_EMAILS and the contact, once each."""
    names = [name for facet in FACETS.values() for need in facet.needs for name in need.names]
    return list(dict.fromkeys(names + [OPERATOR_SETTING, CONTACT_SETTING]))


def known_names() -> List[str]:
    """declared_names() and every alias."""
    aliases = [name for facet in FACETS.values() for need in facet.needs for name in need.aliases]
    return list(dict.fromkeys(declared_names() + aliases))
