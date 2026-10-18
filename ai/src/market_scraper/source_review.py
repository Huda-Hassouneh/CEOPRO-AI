"""
KEEL - Human-in-the-loop review for a discovered data source.

The real gap this closes (found tracing a live tenant with 807 non-ALLOWED
data_sources and zero collected competitor_prices/market_observations/
reviews, despite 03851fb correctly identifying 167 real, in-scope, tracked
competitors): discovery.py's evaluate_candidate()/evaluate_source() were
always working exactly as designed - a fully automated discovery run never
supplies real terms_evidence (there is no way for an automated crawl to
know a website's Terms of Service actually permit scraping), so
policy.py::evaluate_source() correctly lands every discovered source at
either BLOCKED (robots.txt disallows, or the URL itself is invalid) or
RESTRICTED ("terms have not been reviewed; manual approval is required") -
never ALLOWED. That's not a bug, it's "Collection Policy Engine required
by MASTER_SPEC_v4 section 13" doing its job: a real human has to confirm a
site's terms before this system scrapes it, exactly like policy_cli.py's
own --terms-permit flag already requires for a manual `register-source`
call. The actual gap was that this human step existed only as a CLI
command an operator could run - there was no way for an actual tenant
owner/admin to review and approve a source discovered for THEIR OWN
account through the product itself. This module is that missing step,
reusing evaluate_source()/record_policy_decision() exactly as-is - it adds
zero new policy logic, only a real caller for the human-decision inputs
those functions already require.

Never converts a source that must stay BLOCKED: this re-runs the SAME
real robots.txt check evaluate_candidate() itself does (in case the
source's technical controls changed since discovery), so a source whose
robots.txt now disallows crawling comes back BLOCKED again regardless of
what the reviewer answered on terms - exactly like it would if this
review had never happened. A reviewer answering "no" on terms is a real,
explicit rejection (BLOCKED), not left RESTRICTED - the whole point of
asking is to get a real decision, not a second unreviewed state.
"""
from typing import Optional

from src.market_scraper import data_access
from src.market_scraper.discovery import _fetch_robots_allows
from src.market_scraper.policy import SourceCapabilities, evaluate_source

_TERMINAL_STATUS = "ALLOWED"


def review_source(
    conn, tenant_id: str, source_id: str, reviewer_user_id: str,
    terms_permit: bool, reviewer_reference: str,
) -> dict:
    """
    Records a real human decision on whether this source's own Terms of
    Service permit automated collection, then re-runs the exact same
    policy.py::evaluate_source() the automated discovery path uses - the
    reviewer's answer is the ONE real input this function adds; every
    other rule (robots.txt, URL validity, method selection) is unchanged.

    reviewer_reference is required and must be a real, non-empty note the
    reviewer wrote (e.g. "checked example.com/terms on 2026-09-29 - public
    catalog, no anti-scraping clause") - this is what record_policy_
    decision() persists as approval_reference on an ALLOWED outcome, and
    what's recorded in technical_restrictions either way for a real audit
    trail, never a fabricated/auto-generated string.

    Returns the resulting decision dict; raises ValueError for a source
    that doesn't exist, is already ALLOWED (nothing to review), or an
    empty reference.
    """
    if not reviewer_reference or not reviewer_reference.strip():
        raise ValueError("reviewer_reference is required and must describe what was actually reviewed")

    source = data_access.load_source(conn, tenant_id, source_id)
    if source is None:
        raise ValueError("source not found")
    if source["policy_status"] == _TERMINAL_STATUS:
        raise ValueError("source is already ALLOWED - nothing to review")

    # Re-checked live, not trusted from discovery time - a site's own
    # robots.txt can change between when it was discovered and when a
    # human gets to review it; this is the same real fetch discovery.py::
    # evaluate_candidate() already performs, never a cached assumption.
    technical_ok = _fetch_robots_allows(source["source_url"])

    decision = evaluate_source(SourceCapabilities(
        source_url=source["source_url"],
        public_web_collection_possible=True,
        terms_permit_collection=terms_permit,
        technical_controls_permit_collection=technical_ok,
    ))

    is_allowed = decision.status.value == _TERMINAL_STATUS
    data_access.record_policy_decision(
        conn, tenant_id, source_id, decision,
        restrictions={
            **(source["technical_restrictions"] or {}),
            "terms_review": "yes" if terms_permit else "no",
            "reviewed_by_user_id": reviewer_user_id,
            "reviewer_reference": reviewer_reference,
        },
        rate_limit=source.get("rate_limit_per_minute") or 30,
        collector_key=source.get("collector_key") or "standards",
        render_javascript=source.get("render_javascript") or False,
        approval_reference=reviewer_reference if is_allowed else None,
        approved_by=reviewer_user_id if is_allowed else None,
        retention_days=source.get("retention_days") or 90,
        contains_personal_data=source.get("contains_personal_data") or False,
    )

    return {
        "source_id": source_id,
        "status": decision.status.value,
        "method": decision.method.value if decision.method else None,
        "justification": decision.justification,
    }
