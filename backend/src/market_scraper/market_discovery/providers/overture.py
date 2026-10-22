"""Overture Maps places: an open dataset of businesses and places worldwide
(tens of millions, MENA included), published by the Overture Maps
Foundation from Meta, Microsoft, Foursquare and other contributors under
the CDLA-Permissive-2.0 licence. Keyless and free: it is read straight
from the Foundation's public bucket.

The release is a set of GeoParquet files sorted by location. Each file's
footer says which part ("row group", ~20,000 places) covers which area, so
a scan downloads the footers once (kept in OVERTURE_CACHE_DIR) and then only
the few row groups around the company - a few MB for a city - never the
whole dataset.

A place is a candidate when its Overture category or its name says it does
what the company does: the industry's own words and map types, or the
owner's own description. Each one links to where it came from - its
business page on Facebook (Meta's records), its Foursquare venue, or its
own website.

OVERTURE_BASE_URL points at a mirror; OVERTURE_RELEASE pins a release
(default: the newest); DISCOVERY_DISABLE_OVERTURE=true turns it off.
"""
import hashlib
import hmac
import io
import logging
import math
import os
import pickle
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

import httpx

from src.market_scraper.market_discovery import industries
from src.market_scraper.market_discovery.matching import distance_km
from src.market_scraper.market_discovery.models import Candidate, DiscoveryQuery, ProviderResult
from src.market_scraper.market_discovery.providers.osm import _name_pattern

logger = logging.getLogger("KEEL_MARKET_DISCOVERY")
NAME = "overture"
BASE_URL = os.getenv("OVERTURE_BASE_URL", "https://overturemaps-us-west-2.s3.amazonaws.com/").rstrip("/") + "/"
CACHE_DIR = os.getenv("OVERTURE_CACHE_DIR", os.path.join(os.path.expanduser("~"), ".cache", "keel", "overture"))
MAX_RADIUS_KM = 30.0
MIN_CONFIDENCE = float(os.getenv("OVERTURE_MIN_CONFIDENCE", "0.25"))
MAX_CANDIDATES = int(os.getenv("OVERTURE_MAX_CANDIDATES", "1500"))
COLUMNS = ["id", "names", "basic_category", "taxonomy", "websites", "socials", "phones", "addresses",
           "sources", "confidence", "operating_status", "bbox"]
# Words too general to say what a business does ("Software company").
_GENERAL = {"company", "companies", "shop", "shops", "store", "stores", "service", "services", "center", "centre",
            "business", "office", "and", "the", "for", "of", "llc", "co", "group", "other", "general", "local",
            "food", "delivery", "online", "retail", "home", "place", "point", "interest", "establishment",
            "real", "agent", "agency", "management", "professional", "b2b", "corporate", "solution", "solutions",
            "house", "court", "medical"}
_lock = threading.Lock()
_index: Dict[str, dict] = {}


def available():
    if os.getenv("DISCOVERY_DISABLE_OVERTURE", "").lower() in ("1", "true", "yes"):
        return False, "disabled"
    try:
        import pyarrow.parquet  # noqa: F401
    except ImportError:
        return False, "not_installed"
    return True, None


class _RangeFile(io.RawIOBase):
    """A remote file read with HTTP range requests, for the Parquet reader."""

    def __init__(self, url: str, client: httpx.Client, size: Optional[int] = None):
        self.url, self.client, self.pos = url, client, 0
        self.size = size if size is not None else int(client.head(url).headers["content-length"])

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = offset if whence == 0 else (self.pos + offset if whence == 1 else self.size + offset)
        return self.pos

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        if n <= 0 or self.pos >= self.size:
            return b""
        end = min(self.pos + n, self.size) - 1
        response = self.client.get(self.url, headers={"Range": f"bytes={self.pos}-{end}"})
        response.raise_for_status()
        self.pos += len(response.content)
        return response.content

    def readinto(self, buffer):
        data = self.read(len(buffer))
        buffer[:len(data)] = data
        return len(data)


def _client() -> httpx.Client:
    return httpx.Client(timeout=60, follow_redirects=True,
                        headers={"User-Agent": os.getenv("MARKET_RESEARCH_USER_AGENT", "KEEL-MarketResearch/1.0")})


def _list(client: httpx.Client, prefix: str, delimiter: Optional[str] = None) -> Tuple[List[Tuple[str, int]], List[str]]:
    params = {"list-type": "2", "prefix": prefix}
    if delimiter:
        params["delimiter"] = delimiter
    keys, prefixes, token = [], [], None
    while True:
        if token:
            params["continuation-token"] = token
        response = client.get(BASE_URL, params=params)
        response.raise_for_status()
        text = response.text
        keys += [(k, int(s)) for k, s in re.findall(r"<Key>([^<]+)</Key>.*?<Size>(\d+)</Size>", text, re.S)]
        prefixes += re.findall(r"<Prefix>([^<]+)</Prefix>", text)
        token = (re.findall(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", text) or [None])[0]
        if not token:
            return keys, prefixes


def _release(client: httpx.Client) -> str:
    pinned = os.getenv("OVERTURE_RELEASE")
    if pinned:
        return pinned
    _keys, prefixes = _list(client, "release/", "/")
    releases = sorted(p.split("/")[1] for p in prefixes if re.match(r"release/\d{4}-\d{2}-\d{2}", p))
    if not releases:
        raise ValueError("no Overture release listed")
    return releases[-1]


def _cache_key() -> Optional[bytes]:
    """Key that signs the on-disk index. Without one the cache is neither read nor written."""
    secret = os.getenv("OVERTURE_CACHE_SIGNING_KEY") or os.getenv("JWT_SECRET")
    return hashlib.sha256(b"overture-index:" + secret.encode()).digest() if secret else None


def _read_signed_index(path: str) -> Optional[dict]:
    """Unpickle only bytes whose HMAC matches; anyone able to write the cache dir cannot plant code."""
    key = _cache_key()
    if not key:
        return None
    with open(path, "rb") as handle:
        blob = handle.read()
    with open(path + ".sig", "rb") as handle:
        signature = handle.read()
    if not hmac.compare_digest(hmac.new(key, blob, hashlib.sha256).digest(), signature):
        return None
    return pickle.loads(blob)  # noqa: S301 - signature verified above


def _write_signed_index(path: str, index: dict) -> None:
    key = _cache_key()
    if not key:
        return
    blob = pickle.dumps(index)
    with open(path + ".tmp", "wb") as handle:
        handle.write(blob)
    with open(path + ".sig.tmp", "wb") as handle:
        handle.write(hmac.new(key, blob, hashlib.sha256).digest())
    os.replace(path + ".tmp", path)
    os.replace(path + ".sig.tmp", path + ".sig")


def _load_index(client: httpx.Client) -> dict:
    """{release, files: [(key, size, metadata)]} - footers fetched once per
    release and kept on disk, so later scans start immediately."""
    import pyarrow.parquet as pq

    with _lock:
        release = _release(client)
        if release in _index:
            return _index[release]
        path = os.path.join(CACHE_DIR, f"places-{release}.pickle")
        try:
            cached = _read_signed_index(path)
            if cached is not None:
                _index[release] = cached
                return cached
        except Exception:  # noqa: BLE001 - missing, unsigned, truncated, or written by another pyarrow: rebuild
            pass
        keys, _ = _list(client, f"release/{release}/theme=places/type=place/")
        files = []

        def footer(item):
            key, size = item
            return key, size, pq.ParquetFile(_RangeFile(BASE_URL + key, _client(), size)).metadata

        with ThreadPoolExecutor(max_workers=8) as pool:
            files = list(pool.map(footer, [(k, s) for k, s in keys if k.endswith(".parquet")]))
        index = {"release": release, "files": files}
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            _write_signed_index(path, index)
        except OSError as exc:
            logger.warning("Overture index not cached: %s", exc)
        _index[release] = index
        return index


def _box(query: DiscoveryQuery) -> Tuple[float, float, float, float]:
    radius = min(query.radius_km, MAX_RADIUS_KM)
    dlat = radius / 111.32
    dlon = radius / (111.32 * max(math.cos(math.radians(query.latitude)), 0.01))
    return query.longitude - dlon, query.longitude + dlon, query.latitude - dlat, query.latitude + dlat


def _row_groups(index: dict, box) -> List[Tuple[str, int, object, int]]:
    out = []
    for key, size, meta in index["files"]:
        columns = {meta.schema.column(i).path: i for i in range(meta.num_columns)}
        for group in range(meta.num_row_groups):
            row_group = meta.row_group(group)

            def stat(name, row_group=row_group):
                return row_group.column(columns[name]).statistics

            if (stat("bbox.xmax").max < box[0] or stat("bbox.xmin").min > box[1]
                    or stat("bbox.ymax").max < box[2] or stat("bbox.ymin").min > box[3]):
                continue
            out.append((key, size, meta, group))
    return out


def _words(text: str) -> List[str]:
    return [w[:-1] if len(w) > 4 and w.endswith("s") else w
            for w in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(w) >= 3]


def match_words(query: DiscoveryQuery) -> set:
    """Single words an Overture category must contain: the business's own
    search words and the owner's description - general words left out."""
    words = set()
    for phrase in list(query.keywords) + [query.industry_label or ""]:
        words.update(_words(phrase))
    words.update(query.category_words or ())
    return {w for w in words if w not in _GENERAL}


def match_phrases(query: DiscoveryQuery) -> set:
    """Whole category names from the industry's map tags and place types
    ("fast_food", "guest_house"): matched as a whole, so "food_court" never
    matches a tennis court."""
    return {v.lower() for _k, v in query.osm_tags if v and v not in ("yes",)} | {v.lower() for v in query.google_types}


def _category_names(row: dict) -> List[str]:
    taxonomy = row.get("taxonomy") or {}
    return [n.lower() for n in [row.get("basic_category"), taxonomy.get("primary")] + list(taxonomy.get("alternates") or []) if n]


def category_matches(row: dict, words: set, phrases: set) -> bool:
    if words & _category_words(row):
        return True
    return any(name == phrase or f"_{phrase}_" in f"_{name}_" for name in _category_names(row) for phrase in phrases)


def _category_words(row: dict) -> set:
    words = set()
    for name in _category_names(row):
        words.update(_words(name))
    return words


# Contributors whose category alone is not enough: in MENA cities their
# records put fast-food chains, banks and offices under "pharmacy" or
# "supermarket". Such a record counts only when its name agrees.
_CATEGORY_UNRELIABLE = {"microsoft"}


def _category_trusted(row: dict) -> bool:
    datasets = {(s.get("dataset") or "").lower() for s in row.get("sources") or []} - {"overture", ""}
    return bool(datasets - _CATEGORY_UNRELIABLE)


def _all_names(row: dict) -> List[str]:
    names = row.get("names") or {}
    common = names.get("common") or []
    values = [v for _k, v in common] if isinstance(common, list) else list(common.values())
    return [n for n in [names.get("primary")] + values if n]


def _arabic(text: str) -> bool:
    return any("؀" <= ch <= "ۿ" for ch in text or "")


def _source_url(row: dict) -> Optional[str]:
    for source in row.get("sources") or []:
        dataset, record = (source.get("dataset") or "").lower(), source.get("record_id")
        if dataset == "foursquare" and record:
            return f"https://foursquare.com/v/{record}"
    socials = [s for s in row.get("socials") or [] if isinstance(s, str) and s.startswith("http")]
    if socials:
        return socials[0]
    websites = [w for w in row.get("websites") or [] if isinstance(w, str)]
    return websites[0] if websites else None


def to_candidate(row: dict, query: DiscoveryQuery, matched_category: bool, name_match: bool) -> Optional[Candidate]:
    names = row.get("names") or {}
    primary = (names.get("primary") or "").strip()
    if not primary:
        return None
    common = dict(names.get("common") or []) if isinstance(names.get("common"), list) else (names.get("common") or {})
    english = common.get("en") if not _arabic(common.get("en") or "") else None
    arabic = common.get("ar") or (primary if _arabic(primary) else None)
    box = row.get("bbox") or {}
    lat = (box.get("ymin") + box.get("ymax")) / 2 if box.get("ymin") is not None else None
    lon = (box.get("xmin") + box.get("xmax")) / 2 if box.get("xmin") is not None else None
    address = (row.get("addresses") or [{}])[0] or {}
    taxonomy = row.get("taxonomy") or {}
    category = taxonomy.get("primary") or row.get("basic_category")
    return Candidate(
        name=english or primary, name_ar=arabic,
        source=NAME, source_ref=row["id"], source_url=_source_url(row),
        website=next((w for w in row.get("websites") or [] if isinstance(w, str)), None),
        phone=(row.get("phones") or [None])[0],
        address=", ".join(p for p in (address.get("freeform"), address.get("locality")) if p) or None,
        city=address.get("locality") or query.city, country_code=address.get("country") or query.country_code,
        latitude=lat, longitude=lon, categories=[f"overture:{category}"] if category else [],
        industry_key=query.industry_key if matched_category else None,
        raw={"category": category, "confidence": row.get("confidence"), "name_match": name_match,
             "datasets": sorted({(s.get("dataset") or "") for s in row.get("sources") or []})},
    )


def search(query: DiscoveryQuery) -> ProviderResult:
    ok, reason = available()
    if not ok:
        return ProviderResult(NAME, "skipped", reason=reason)
    if not query.has_location:
        return ProviderResult(NAME, "skipped", reason="no_location")
    import pyarrow.parquet as pq

    wanted, phrases = match_words(query), match_phrases(query)
    pattern = _name_pattern(query.keywords, by_word=query.industry_key == industries.CUSTOM)
    name_re = re.compile(pattern, re.IGNORECASE) if pattern else None
    box = _box(query)
    radius = min(query.radius_km, MAX_RADIUS_KM)
    client = _client()
    try:
        index = _load_index(client)
        groups = _row_groups(index, box)
    except (httpx.HTTPError, ValueError, OSError) as exc:
        logger.warning("Overture index unavailable: %s", type(exc).__name__)
        return ProviderResult(NAME, "failed", reason="unreachable", requests=1)

    def read(item):
        key, size, meta, group = item
        reader = pq.ParquetFile(_RangeFile(BASE_URL + key, _client(), size), metadata=meta)
        return reader.read_row_group(group, columns=COLUMNS).to_pylist()

    found, failures = [], 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(read, g) for g in groups]
        for future in futures:
            try:
                rows = future.result()
            except Exception as exc:  # noqa: BLE001 - one part failing leaves the rest
                failures += 1
                logger.warning("Overture part failed: %s", type(exc).__name__)
                continue
            for row in rows:
                b = row.get("bbox") or {}
                if not (box[0] <= (b.get("xmin") or 999) <= box[1] and box[2] <= (b.get("ymin") or 999) <= box[3]):
                    continue
                if (row.get("operating_status") or "open") not in ("open", None) or (row.get("confidence") or 0) < MIN_CONFIDENCE:
                    continue
                matched_category = category_matches(row, wanted, phrases) and _category_trusted(row)
                text = " ".join(_all_names(row))
                name_match = bool(name_re and name_re.search(text))
                if not (matched_category or name_match):
                    continue
                candidate = to_candidate(row, query, matched_category, name_match)
                if candidate is None or not candidate.source_url:
                    continue  # nothing a person could open to check it
                away = distance_km(query.latitude, query.longitude, candidate.latitude, candidate.longitude)
                if away is not None and away > radius:
                    continue
                found.append((away if away is not None else radius, candidate))
    if groups and failures == len(groups):
        return ProviderResult(NAME, "failed", reason="unreachable", requests=len(groups) + 1)
    found.sort(key=lambda pair: pair[0])
    return ProviderResult(NAME, "ok", [c for _d, c in found[:MAX_CANDIDATES]], requests=len(groups) + 1)
