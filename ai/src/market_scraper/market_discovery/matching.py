"""Turns raw candidates from every source into one entity per business.

Two reports are the same business when they share a website domain (or a
social handle), a phone number, or a normalised name - and, for names that
are only similar, when they are also within a short walk of each other.
Branches of one brand (same name or domain, different places) are kept as
one competitor with its branches listed, since the owner competes with the
brand; the nearest branch gives the distance."""
import math
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Dict, List, Optional
from urllib.parse import urlsplit

from src.market_scraper.discovery import compute_website_identity_key
from src.market_scraper.market_discovery.models import Candidate

SAME_PLACE_METERS = 150
SIMILAR_NAME = 0.86

_AR_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_AR_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي"})
_NON_WORD = re.compile(r"[^\w؀-ۿ]+")
# Words that describe the kind of business rather than name it.
_GENERIC = {
    "the", "and", "co", "company", "llc", "ltd", "inc", "est", "establishment", "group", "jo", "branch",
    "restaurant", "restaurants", "cafe", "coffee", "shop", "store", "stores", "market", "supermarket", "hotel",
    "pharmacy", "bakery", "salon", "center", "centre", "boutique", "trading", "official", "online",
    "al", "el", "مطعم", "مطاعم", "مقهى", "كافيه", "صيدليه", "صيدلية", "فندق", "سوبرماركت", "مخبز", "محل",
    "محلات", "شركه", "مؤسسه", "متجر", "معرض", "فرع", "مركز", "صالون", "و",
}


def normalize_name(name: str) -> str:
    text = unicodedata.normalize("NFKC", name or "").lower()
    text = _AR_DIACRITICS.sub("", text).translate(_AR_FOLD)
    text = re.sub(r"\b(al|el)[-\s]", "", text)
    words = [w for w in _NON_WORD.split(text) if w]
    words = [w[2:] if w.startswith("ال") and len(w) > 4 else w for w in words]
    core = [w for w in words if w not in _GENERIC]
    return " ".join(core or words)


def domain_key(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    if "://" not in url:
        url = "https://" + url
    key = compute_website_identity_key(url)
    host = (urlsplit(url).hostname or "")
    # Linktree-style hosts and map links say nothing about identity.
    if not key or host.endswith(("linktr.ee", "google.com", "goo.gl", "wa.me", "bit.ly")):
        return None
    return key


def phone_key(phone: Optional[str]) -> Optional[str]:
    digits = re.sub(r"\D", "", phone or "")
    return digits[-8:] if len(digits) >= 7 else None


def distance_km(lat1, lon1, lat2, lon2) -> Optional[float]:
    if None in (lat1, lon1, lat2, lon2):
        return None
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass
class Branch:
    latitude: float
    longitude: float
    address: Optional[str]
    distance_km: Optional[float] = None


@dataclass
class Entity:
    """One business, merged from every source that reported it."""
    name: str
    candidates: List[Candidate] = field(default_factory=list)
    branches: List[Branch] = field(default_factory=list)
    name_keys: set = field(default_factory=set)
    domain_keys: set = field(default_factory=set)
    phone_keys: set = field(default_factory=set)

    def add(self, candidate: Candidate) -> None:
        self.candidates.append(candidate)
        self.name_keys.add(normalize_name(candidate.name))
        if candidate.name_ar:
            self.name_keys.add(normalize_name(candidate.name_ar))
        for key in (domain_key(candidate.website), domain_key(candidate.source_url) if candidate.raw.get("social") else None):
            if key:
                self.domain_keys.add(key)
        if phone_key(candidate.phone):
            self.phone_keys.add(phone_key(candidate.phone))
        if candidate.latitude is not None and candidate.longitude is not None:
            near = any(distance_km(b.latitude, b.longitude, candidate.latitude, candidate.longitude) * 1000 < SAME_PLACE_METERS
                       for b in self.branches)
            if not near:
                self.branches.append(Branch(candidate.latitude, candidate.longitude, candidate.address))
        # The display name: prefer a map listing's own name over a web title.
        if not self.candidates[0].latitude and candidate.latitude:
            self.name = candidate.name

    def first(self, attribute: str):
        for candidate in self.candidates:
            value = getattr(candidate, attribute)
            if value not in (None, "", []):
                return value
        return None

    @property
    def sources(self) -> set:
        return {c.source for c in self.candidates}

    @property
    def online_only(self) -> bool:
        return all(c.online_only for c in self.candidates)

    def best_rating(self):
        rated = [c for c in self.candidates if c.rating is not None]
        if not rated:
            return None, None
        best = max(rated, key=lambda c: c.review_count or 0)
        return best.rating, max(c.review_count or 0 for c in rated) or None

    def categories(self) -> List[str]:
        seen = []
        for candidate in self.candidates:
            for category in candidate.categories:
                if category not in seen:
                    seen.append(category)
        return seen[:12]

    def industry_keys(self) -> List[str]:
        return [c.industry_key for c in self.candidates if c.industry_key]


def _same(entity: Entity, candidate: Candidate) -> bool:
    if domain_key(candidate.website) and domain_key(candidate.website) in entity.domain_keys:
        return True
    if candidate.raw.get("social") and domain_key(candidate.source_url) in entity.domain_keys:
        return True
    if phone_key(candidate.phone) and phone_key(candidate.phone) in entity.phone_keys:
        return True
    names = {normalize_name(candidate.name)} | ({normalize_name(candidate.name_ar)} if candidate.name_ar else set())
    names.discard("")
    if names & entity.name_keys:
        return True
    if candidate.latitude is None:
        return False
    for branch in entity.branches:
        meters = (distance_km(branch.latitude, branch.longitude, candidate.latitude, candidate.longitude) or 1e9) * 1000
        if meters < SAME_PLACE_METERS and any(
                SequenceMatcher(None, a, b).ratio() >= SIMILAR_NAME for a in names for b in entity.name_keys):
            return True
    return False


def merge(candidates: List[Candidate]) -> List[Entity]:
    entities: List[Entity] = []
    index: Dict[str, Entity] = {}
    # Map listings first so each entity is anchored on a real place.
    for candidate in sorted(candidates, key=lambda c: (c.latitude is None, c.source)):
        quick = [index.get(k) for k in (
            "d:" + (domain_key(candidate.website) or ""), "p:" + (phone_key(candidate.phone) or ""),
            "n:" + normalize_name(candidate.name)) if not k.endswith(":")]
        entity = next((e for e in quick if e is not None), None)
        if entity is None:
            entity = next((e for e in entities if _same(e, candidate)), None)
        if entity is None:
            entity = Entity(name=candidate.name)
            entities.append(entity)
        entity.add(candidate)
        for key in entity.domain_keys:
            index["d:" + key] = entity
        for key in entity.phone_keys:
            index["p:" + key] = entity
        for key in entity.name_keys:
            if key:
                index["n:" + key] = entity
    return entities


def is_self(entity: Entity, own_name: Optional[str], own_website: Optional[str]) -> bool:
    if own_website and domain_key(own_website) and domain_key(own_website) in entity.domain_keys:
        return True
    own = normalize_name(own_name or "")
    return bool(own) and own in entity.name_keys
