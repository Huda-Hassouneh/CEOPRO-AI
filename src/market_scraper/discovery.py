"""
CEOPRO AI - Dynamic Competitor Discovery.

Given a product name, decides which candidate seller URL is technically
and contractually permitted to be collected from, tenant-scoped
throughout. Real constraint, flagged rather than hidden: identifying
WHICH URLs sell a given product requires a general web-search capability
(Bing/Google Custom Search/SerpApi, etc.) - no such API is configured
with credentials in this environment, the same category of gap already
documented for Google Places/Amazon PA-API. discover_candidates() takes
search results as input rather than performing the search itself for
that reason - a production deployment wires a real search API's results
into this same function; this module's own logic (the technical/policy
decision, tenant-scoped persistence) is the real implementation, not a
stand-in.

Never fabricates permission: technical_controls_permit_collection comes
from an actual robots.txt fetch, never assumed. terms_permit_collection
is only ever True when the caller supplies real, checkable evidence (e.g.
the site's own robots.txt explicitly documents its pages as crawlable) -
without that evidence it stays unknown, and evaluate_source() (policy.py)
correctly returns RESTRICTED rather than ALLOWED. A RESTRICTED/BLOCKED
decision is not a failure to hide - it's the correct, honest outcome
when a discovered source hasn't been reviewed, and it still records the
candidate URL as evidence that a seller was found, per spec: "log the
details it did find along with the exact URL discovered."
"""
import json
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlsplit

from src.market_scraper import data_access
from src.market_scraper.policy import SourceCapabilities, evaluate_source, is_public_http_url
from src.market_scraper.sector_detection import MANUFACTURER_SIGNAL_WORDS


def looks_like_manufacturer_or_wholesale(candidate: "CandidateSource", brand_tokens: set) -> bool:
    """
    Generic across every vertical (no electronics-specific logic): a
    candidate is deprioritized as a likely manufacturer/wholesaler, not a
    retail storefront, when either (a) its own domain name contains a
    token that is also the product's brand/manufacturer name - e.g. a
    product named "Arduino Nano" sold at a domain containing "arduino" is
    almost certainly the manufacturer's own store, not a third-party
    retailer - or (b) its title/URL text contains an explicit wholesale/
    distributor/B2B signal word. Both signals are lexical, not a claim of
    certainty - see this module's own docstring on the real limits of a
    heuristic without a real classification API.
    """
    hostname = urlsplit(candidate.url).hostname or ""
    host_tokens = set(part for part in hostname.replace("-", ".").split(".") if part)
    if brand_tokens & host_tokens:
        return True
    haystack = f"{candidate.title} {candidate.url}".lower()
    return any(word in haystack for word in MANUFACTURER_SIGNAL_WORDS)


@dataclass(frozen=True)
class CandidateSource:
    """One result from an external search for `product_name` - url/title
    come from whatever search backend the caller used; nothing here is
    hardcoded per-product."""
    product_name: str
    url: str
    title: str


@dataclass(frozen=True)
class DiscoveryDecision:
    candidate: CandidateSource
    technical_controls_permit_collection: Optional[bool]
    policy_status: str  # ALLOWED / RESTRICTED / BLOCKED
    justification: str
    robots_evidence: Optional[str]


_ROBOTS_FETCH_TIMEOUT = 15


def _fetch_robots_allows(url: str) -> Optional[bool]:
    """
    True/False from a real robots.txt fetch; None if robots.txt itself
    couldn't be read - never treated as silent permission by the caller.

    Reimplements RobotFileParser.read()'s own fetch (same HTTP-status
    handling: 401/403 -> disallow_all, other 4xx -> allow_all, matching
    the real convention that a missing robots.txt means unrestricted) but
    with an explicit timeout - the stdlib's own .read() calls
    urllib.request.urlopen() with NO timeout at all, a real hang risk this
    module lived with silently until a caller with enough concurrent
    robots.txt fetches (direct_search.py's per-domain lookups, run in an
    8-worker thread pool) exposed it live: a single unresponsive server
    left the whole run stuck indefinitely instead of failing fast into
    the "unreviewed, not permitted" path this function already correctly
    returns for every other failure mode.
    """
    parsed = urlsplit(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(robots_url)
    try:
        f = urllib.request.urlopen(robots_url, timeout=_ROBOTS_FETCH_TIMEOUT)
    except urllib.error.HTTPError as err:
        if err.code in (401, 403):
            parser.disallow_all = True
        elif 400 <= err.code < 500:
            parser.allow_all = True
        else:
            return None
        err.close()
    except Exception:
        return None
    else:
        raw = f.read()
        parser.parse(raw.decode("utf-8", "surrogateescape").splitlines())
    return parser.can_fetch("*", url)


def evaluate_candidate(candidate: CandidateSource, terms_evidence: Optional[str] = None) -> DiscoveryDecision:
    """
    Runs the same public-URL + Collection Policy Engine decision
    (policy.py::evaluate_source, already used by policy_cli.py for every
    other source in this codebase) against one dynamically-discovered
    candidate.

    terms_evidence: pass real, quotable text (e.g. a robots.txt comment
    that explicitly states pages are crawlable) only when it genuinely
    exists for this exact domain - it becomes the policy record's
    approval_reference. Omit it (default) for a candidate with no such
    evidence; the decision then correctly comes back RESTRICTED, not
    ALLOWED, and no data is collected from it.
    """
    if not is_public_http_url(candidate.url):
        return DiscoveryDecision(candidate, None, "BLOCKED", "not a public http(s) URL", None)

    technical_ok = _fetch_robots_allows(candidate.url)
    if technical_ok is None:
        return DiscoveryDecision(
            candidate, None, "RESTRICTED",
            "robots.txt could not be read - treated as unreviewed, not permitted", None,
        )
    if not technical_ok:
        return DiscoveryDecision(candidate, False, "BLOCKED", "robots.txt disallows this path", None)

    decision = evaluate_source(SourceCapabilities(
        source_url=candidate.url,
        public_web_collection_possible=True,
        terms_permit_collection=True if terms_evidence else None,
        technical_controls_permit_collection=True,
    ))
    return DiscoveryDecision(candidate, True, decision.status.value, decision.justification, terms_evidence)


def register_tenant_scoped_competitor(
    conn, tenant_id: str, actor_user_id: str, decision: DiscoveryDecision,
    product_id: str, rate_limit: int = 20,
) -> dict:
    """
    Persists a dynamically-discovered candidate strictly scoped to
    `tenant_id` - global_competitors.visibility is always 'PRIVATE' with
    added_by_tenant_id=tenant_id (never 'GLOBAL'), so RLS
    (select_global_competitors: visibility='GLOBAL' OR added_by_tenant_id
    = get_current_tenant()) means Tenant B can never see a competitor
    Tenant A's discovery run found - the exact isolation this feature was
    built for. Returns identifiers plus whatever decision.policy_status
    ended up being (ALLOWED/RESTRICTED/BLOCKED) - the caller decides
    whether to actually run the collector based on that, this function
    only ever records what was found.
    """
    candidate = decision.candidate
    hostname = urlsplit(candidate.url).hostname or candidate.url

    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO global_competitors (competitor_name, website_url, visibility, added_by_tenant_id)
            VALUES (%s, %s, 'PRIVATE', %s)
            ON CONFLICT (added_by_tenant_id, LOWER(competitor_name)) WHERE (visibility = 'PRIVATE')
            DO UPDATE SET website_url = EXCLUDED.website_url
            RETURNING global_competitor_id;
            """,
            (candidate.title or hostname, f"{urlsplit(candidate.url).scheme}://{hostname}", tenant_id),
        )
        competitor_id = cursor.fetchone()[0]

        cursor.execute(
            "INSERT INTO tenant_competitors (tenant_id, global_competitor_id) VALUES (%s, %s) "
            "ON CONFLICT DO NOTHING;",
            (tenant_id, competitor_id),
        )

        cursor.execute(
            "INSERT INTO data_sources (tenant_id, source_name, source_type) "
            "VALUES (%s, %s, 'WEB_SCRAPE') RETURNING source_id;",
            (tenant_id, f"Dynamically discovered: {hostname}"),
        )
        source_id = cursor.fetchone()[0]

        cursor.execute(
            "INSERT INTO competitor_product_mappings "
            "(tenant_id, global_competitor_id, product_id, competitor_product_url, source_id) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING mapping_id;",
            (tenant_id, competitor_id, product_id, candidate.url, source_id),
        )
        mapping_id = cursor.fetchone()[0]

    decision_obj = evaluate_source(SourceCapabilities(
        source_url=candidate.url,
        public_web_collection_possible=True,
        terms_permit_collection=True if decision.robots_evidence else None,
        technical_controls_permit_collection=decision.technical_controls_permit_collection,
    ))
    data_access.record_policy_decision(
        conn, tenant_id, str(source_id), decision_obj,
        restrictions={
            "discovery_method": "dynamic_search",
            "robots_evidence": decision.robots_evidence,
            "candidate_title": candidate.title,
        },
        rate_limit=rate_limit,
        collector_key="standards",
        approval_reference=decision.robots_evidence,
        approved_by=actor_user_id if decision.robots_evidence else None,
        retention_days=30,
        contains_personal_data=False,
    )

    return {
        "competitor_id": str(competitor_id),
        "source_id": str(source_id),
        "mapping_id": str(mapping_id),
        "policy_status": decision_obj.status.value,
        "product_url": candidate.url,
        "competitor_name": candidate.title or hostname,
    }
