"""
KEEL - ISO 3166-1 alpha-2 country codes, shared reference data.

Standard, stable, publicly-documented codes (the same ones already stored
in companies.country_code/operating_countries and global_competitors.
country_code) - not fabricated or guessed, and not industry/vertical-
specific. Two real, generic uses this module exists for:

1. sector_detection.py::resolve_tenant_geo_scope() - turning a tenant's
   stored country code(s) into a human-readable name a search engine can
   actually use as a geographic hint ("Jordan", not the bare code "JO").
2. discovery.py::infer_country_code_from_domain() - the inverse direction,
   recognizing a discovered URL's own country-code top-level domain
   (e.g. "sparkfun.com" -> no signal, "somefactory.cn" -> "CN") as a real,
   free, zero-credential piece of evidence about where a candidate is
   actually based.

Neither use requires every country on Earth to be listed for correctness -
an unrecognized code degrades to itself (name lookup) or None (ccTLD
lookup), the same "unknown, never guessed" discipline every other
heuristic in this package already follows. This list intentionally covers
the common, real set rather than claiming exhaustive ISO 3166-1 coverage.
"""

# code -> common English name. Deliberately NOT claimed exhaustive - see
# module docstring. A caller doing a name lookup falls back to the bare
# code itself for anything not listed here, never a guess.
COUNTRY_NAMES = {
    "AE": "United Arab Emirates", "AF": "Afghanistan", "AL": "Albania", "AM": "Armenia",
    "AO": "Angola", "AR": "Argentina", "AT": "Austria", "AU": "Australia", "AZ": "Azerbaijan",
    "BA": "Bosnia and Herzegovina", "BD": "Bangladesh", "BE": "Belgium", "BG": "Bulgaria",
    "BH": "Bahrain", "BO": "Bolivia", "BR": "Brazil", "BY": "Belarus", "CA": "Canada",
    "CH": "Switzerland", "CL": "Chile", "CM": "Cameroon", "CN": "China", "CO": "Colombia",
    "CR": "Costa Rica", "CY": "Cyprus", "CZ": "Czech Republic", "DE": "Germany",
    "DK": "Denmark", "DO": "Dominican Republic", "DZ": "Algeria", "EC": "Ecuador",
    "EE": "Estonia", "EG": "Egypt", "ES": "Spain", "ET": "Ethiopia", "FI": "Finland",
    "FR": "France", "GB": "United Kingdom", "GE": "Georgia", "GH": "Ghana", "GR": "Greece",
    "GT": "Guatemala", "HK": "Hong Kong", "HN": "Honduras", "HR": "Croatia", "HU": "Hungary",
    "ID": "Indonesia", "IE": "Ireland", "IL": "Israel", "IN": "India", "IQ": "Iraq",
    "IR": "Iran", "IS": "Iceland", "IT": "Italy", "JM": "Jamaica", "JO": "Jordan",
    "JP": "Japan", "KE": "Kenya", "KH": "Cambodia", "KR": "South Korea", "KW": "Kuwait",
    "KZ": "Kazakhstan", "LB": "Lebanon", "LK": "Sri Lanka", "LT": "Lithuania", "LU": "Luxembourg",
    "LV": "Latvia", "LY": "Libya", "MA": "Morocco", "MD": "Moldova", "MK": "North Macedonia",
    "MM": "Myanmar", "MN": "Mongolia", "MT": "Malta", "MX": "Mexico", "MY": "Malaysia",
    "NG": "Nigeria", "NI": "Nicaragua", "NL": "Netherlands", "NO": "Norway", "NP": "Nepal",
    "NZ": "New Zealand", "OM": "Oman", "PA": "Panama", "PE": "Peru", "PH": "Philippines",
    "PK": "Pakistan", "PL": "Poland", "PS": "Palestine", "PT": "Portugal", "PY": "Paraguay",
    "QA": "Qatar", "RO": "Romania", "RS": "Serbia", "RU": "Russia", "SA": "Saudi Arabia",
    "SD": "Sudan", "SE": "Sweden", "SG": "Singapore", "SI": "Slovenia", "SK": "Slovakia",
    "SN": "Senegal", "SV": "El Salvador", "SY": "Syria", "TH": "Thailand", "TN": "Tunisia",
    "TR": "Turkey", "TW": "Taiwan", "TZ": "Tanzania", "UA": "Ukraine", "UG": "Uganda",
    "US": "United States", "UY": "Uruguay", "UZ": "Uzbekistan", "VE": "Venezuela",
    "VN": "Vietnam", "YE": "Yemen", "ZA": "South Africa", "ZM": "Zambia", "ZW": "Zimbabwe",
}


def country_name(code: str) -> str:
    """Human-readable name for a stored ISO code, falling back to the bare
    code itself (never a fabricated name) when it isn't in COUNTRY_NAMES."""
    if not code:
        return ""
    return COUNTRY_NAMES.get(code.upper(), code)


# ccTLD -> ISO 3166-1 alpha-2, for the handful of real cases where the
# domain suffix differs from the country's own code. Every ccTLD NOT
# listed here is assumed to equal its own uppercase (true for the large
# majority - "somefactory.jo" -> "JO", "somefactory.cn" -> "CN"); this
# dict only needs to hold the exceptions.
CCTLD_CODE_OVERRIDES = {
    "uk": "GB",
}

# Generic TLDs give no real geographic signal at all - explicitly listed
# so a caller can distinguish "checked and found nothing" from "not a
# recognized ccTLD" (both currently resolve to None from infer_country_
# code_from_domain(), but keeping this list means that function never
# has to guess between "some new ccTLD I don't recognize" and "this is
# deliberately non-geographic").
GENERIC_TLDS = {
    "com", "net", "org", "io", "co", "info", "biz", "shop", "store",
    "online", "app", "dev", "ai", "tech", "xyz", "site", "me",
}
