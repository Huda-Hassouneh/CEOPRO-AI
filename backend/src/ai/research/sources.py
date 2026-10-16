"""
How much weight a public source carries, and which jurisdiction it speaks for.

Official sources are governments, regulators, customs and tax authorities,
standards bodies, central banks and intergovernmental trade bodies. They
are preferred for anything legal, tax, customs or regulatory, and only an
official source can support a statement that something is a current legal
requirement (citations.py enforces that). Everything else is a secondary
source unless the page belongs to the business or manufacturer it
describes.
"""
from typing import Optional
from urllib.parse import urlsplit

OFFICIAL = "official"
PRIMARY = "primary"
SECONDARY = "secondary"

# Official bodies whose domains don't end in a government suffix.
_OFFICIAL_DOMAINS = {
    # Jordan
    "jfda.jo": "JO", "jsmo.gov.jo": "JO", "customs.gov.jo": "JO", "istd.gov.jo": "JO", "cbj.gov.jo": "JO",
    "mit.gov.jo": "JO", "dos.gov.jo": "JO",
    # Saudi Arabia
    "zatca.gov.sa": "SA", "sfda.gov.sa": "SA", "saso.gov.sa": "SA", "saber.sa": "SA", "mc.gov.sa": "SA",
    "sama.gov.sa": "SA", "stats.gov.sa": "SA",
    # United Arab Emirates
    "tax.gov.ae": "AE", "moiat.gov.ae": "AE", "u.ae": "AE", "dubaicustoms.gov.ae": "AE", "centralbank.ae": "AE",
    "fcsc.gov.ae": "AE", "moec.gov.ae": "AE",
    # Egypt, Türkiye, Gulf
    "eta.gov.eg": "EG", "customs.gov.eg": "EG", "cbe.org.eg": "EG", "ticaret.gov.tr": "TR", "gib.gov.tr": "TR",
    "tcmb.gov.tr": "TR", "gso.org.sa": "GCC", "gcc-sg.org": "GCC",
    # International
    "wto.org": "International", "worldbank.org": "International", "wits.worldbank.org": "International",
    "intracen.org": "International", "macmap.org": "International", "un.org": "International",
    "unctad.org": "International", "comtrade.un.org": "International", "wcoomd.org": "International",
    "imf.org": "International", "fao.org": "International", "iccwbo.org": "International",
    "europa.eu": "EU", "trade-tariff.service.gov.uk": "GB", "hts.usitc.gov": "US",
}
_GOVERNMENT_SUFFIXES = (".gov", ".gov.", ".gob.", ".gouv.", ".go.", ".mil.")
_CCTLD = {
    "jo": "JO", "sa": "SA", "ae": "AE", "kw": "KW", "qa": "QA", "bh": "BH", "om": "OM", "eg": "EG", "lb": "LB",
    "iq": "IQ", "ps": "PS", "ma": "MA", "dz": "DZ", "tn": "TN", "tr": "TR", "uk": "GB", "cn": "CN", "in": "IN",
    "de": "DE", "fr": "FR", "it": "IT", "es": "ES",
}


def host_of(url: str) -> str:
    host = (urlsplit(url or "").hostname or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def _official_jurisdiction(host: str) -> Optional[str]:
    for domain, jurisdiction in _OFFICIAL_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return jurisdiction
    padded = f".{host}."
    if any(suffix in padded for suffix in _GOVERNMENT_SUFFIXES) or host.endswith(".gov"):
        tld = host.rsplit(".", 1)[-1]
        return _CCTLD.get(tld, "US" if tld == "gov" else None) or "Government"
    return None


def credibility(url: str) -> str:
    return OFFICIAL if _official_jurisdiction(host_of(url)) else SECONDARY


def jurisdiction(url: str) -> Optional[str]:
    """The jurisdiction an official source speaks for (None for other sources)."""
    return _official_jurisdiction(host_of(url))


def organisation(url: str, site_name: Optional[str] = None) -> str:
    return (site_name or "").strip() or host_of(url)
