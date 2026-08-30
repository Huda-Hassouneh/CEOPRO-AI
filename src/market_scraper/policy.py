"""Collection Policy Engine required by MASTER_SPEC_v4 section 13."""

import ipaddress
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from urllib.parse import urlsplit


class SourceStatus(str, Enum):
    ALLOWED = "ALLOWED"
    RESTRICTED = "RESTRICTED"
    BLOCKED = "BLOCKED"


class CollectionMethod(str, Enum):
    OFFICIAL_API = "OFFICIAL_API"
    RSS = "RSS"
    STRUCTURED_DATA = "STRUCTURED_DATA"
    WEB_SCRAPE = "WEB_SCRAPE"


@dataclass(frozen=True)
class SourceCapabilities:
    source_url: str
    official_api_url: Optional[str] = None
    rss_url: Optional[str] = None
    has_structured_data: bool = False
    public_web_collection_possible: bool = False
    terms_permit_collection: Optional[bool] = None
    technical_controls_permit_collection: Optional[bool] = None


@dataclass(frozen=True)
class PolicyDecision:
    status: SourceStatus
    method: Optional[CollectionMethod]
    collection_url: str
    justification: str


def is_public_http_url(url: str) -> bool:
    """Reject malformed, local, credential-bearing, and literal private-network URLs."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        return False
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
        return False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return True
    return address.is_global


def evaluate_source(capabilities: SourceCapabilities) -> PolicyDecision:
    """Choose the safest supported method; uncertainty never becomes permission."""
    candidate_urls = [
        capabilities.source_url,
        capabilities.official_api_url,
        capabilities.rss_url,
    ]
    if any(url and not is_public_http_url(url) for url in candidate_urls):
        return PolicyDecision(
            SourceStatus.BLOCKED,
            None,
            capabilities.source_url,
            "Source contains an invalid or non-public URL.",
        )
    if capabilities.terms_permit_collection is False:
        return PolicyDecision(
            SourceStatus.BLOCKED,
            None,
            capabilities.source_url,
            "Source terms prohibit automated collection.",
        )
    if capabilities.technical_controls_permit_collection is False:
        return PolicyDecision(
            SourceStatus.BLOCKED,
            None,
            capabilities.source_url,
            "Source technical controls prohibit automated collection.",
        )
    if capabilities.terms_permit_collection is None:
        return PolicyDecision(
            SourceStatus.RESTRICTED,
            None,
            capabilities.source_url,
            "Source terms have not been reviewed; manual approval is required.",
        )

    if capabilities.official_api_url:
        return PolicyDecision(
            SourceStatus.ALLOWED,
            CollectionMethod.OFFICIAL_API,
            capabilities.official_api_url,
            "Official public API is the preferred available collection method.",
        )
    if capabilities.rss_url:
        return PolicyDecision(
            SourceStatus.ALLOWED,
            CollectionMethod.RSS,
            capabilities.rss_url,
            "Public RSS/feed is preferred over page scraping.",
        )
    if capabilities.has_structured_data:
        return PolicyDecision(
            SourceStatus.ALLOWED,
            CollectionMethod.STRUCTURED_DATA,
            capabilities.source_url,
            "Public structured page data is available.",
        )
    if capabilities.public_web_collection_possible:
        if capabilities.technical_controls_permit_collection is None:
            return PolicyDecision(
                SourceStatus.RESTRICTED,
                None,
                capabilities.source_url,
                "Robots and technical collection controls require review.",
            )
        return PolicyDecision(
            SourceStatus.ALLOWED,
            CollectionMethod.WEB_SCRAPE,
            capabilities.source_url,
            "Controlled collection of public pages is permitted; no safer structured source is available.",
        )
    return PolicyDecision(
        SourceStatus.RESTRICTED,
        None,
        capabilities.source_url,
        "No approved, technically supported collection method is available.",
    )
