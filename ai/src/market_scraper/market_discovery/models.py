"""The shapes passed between discovery providers, matching and storage."""
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

_DOMAIN = re.compile(r"^[\w.-]+\.[a-z]{2,}(?:[/:?#].*)?$", re.IGNORECASE)


def web_address(value: Optional[str]) -> Optional[str]:
    """A website as sources give it ("tottis.jo", "www.x.com/menu",
    "https://x.com") as a full https:// address, or None when it isn't one."""
    text = (value or "").strip().split(";")[0].strip()
    if not text:
        return None
    if re.match(r"^https?://", text, re.IGNORECASE):
        return text
    if text.startswith("//"):
        return "https:" + text
    return "https://" + text if _DOMAIN.match(text) else None


@dataclass
class DiscoveryQuery:
    """What one company's discovery run looks for."""
    tenant_id: str
    industry_key: str
    industry_label: str
    keywords: List[str]                      # search phrases (industry + product categories)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    radius_km: float = 5.0
    city: Optional[str] = None
    country_code: Optional[str] = None
    language: str = "en"
    own_name: Optional[str] = None           # the company itself, never reported as a competitor
    own_website: Optional[str] = None
    osm_tags: Tuple[Tuple[str, str], ...] = ()
    google_types: Tuple[str, ...] = ()
    category_words: Tuple[str, ...] = ()     # English category words for a type described in another language
    specialty_terms: Tuple[str, ...] = ()    # what this company specifically sells (relevance.py)
    category_paths: Tuple[Tuple[str, ...], ...] = ()  # the segments it operates in (category_taxonomy.py)
    max_results: int = int(os.getenv("DISCOVERY_MAX_RESULTS", "1000"))

    @property
    def has_location(self) -> bool:
        return self.latitude is not None and self.longitude is not None


@dataclass
class Candidate:
    """One business as reported by one source."""
    name: str
    source: str                              # openstreetmap | google_places | google_search | apify_google_maps | searxng
    source_ref: str                          # the source's own id for it
    source_url: Optional[str] = None         # where a person can check it
    name_ar: Optional[str] = None
    website: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    categories: List[str] = field(default_factory=list)
    industry_key: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    price_level: Optional[int] = None
    online_only: bool = False                # found as a website, not a place
    raw: dict = field(default_factory=dict)  # a trimmed copy of what the source returned

    def __post_init__(self):
        # Map listings often store "example.jo" with no scheme: as given, the
        # site reader refused it and the app linked to a relative path.
        self.website = web_address(self.website)


@dataclass
class ProviderResult:
    provider: str
    status: str                              # ok | skipped | failed
    candidates: List[Candidate] = field(default_factory=list)
    reason: Optional[str] = None
    requests: int = 0
