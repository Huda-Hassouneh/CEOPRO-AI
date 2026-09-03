"""
CEOPRO AI - Per-Tenant Locale Configuration.
Resolves date-order and decimal-separator conventions from the tenant's
registered country (companies.country_code - already in the schema, no
new column needed) instead of a single global environment variable.

Scope limitation: this resolves one locale per tenant, from
companies.country_code, the company's primary registered market. A
tenant whose companies.operating_countries lists more than one country
is not split by country here - there is no per-file or per-source
country field in the current schema (data_sources has no country
column) to resolve against instead. Closing that fully requires a
schema change and is out of scope until confirmed.
"""
from typing import Dict, List, NamedTuple, Optional

# Day-first (DD/MM/YYYY) is the majority global convention; month-first
# (MM/DD/YYYY) is the exception. This list covers the common cases -
# review against your actual 16-country footprint before treating any
# entry not yet verified against a real customer file as confirmed.
MONTH_FIRST_COUNTRIES = {"US", "FM", "PW", "PH"}

# Decimal separator convention by country: "period" -> 1,234.56, "comma" -> 1.234,56.
# Populated for MENA and francophone North Africa per this deployment's
# stated footprint; every value here is an assumption pending your
# team's confirmation, not a verified fact about that country's invoicing
# conventions.
COUNTRY_DECIMAL_STYLE: Dict[str, str] = {
    "JO": "period", "SA": "period", "AE": "period", "QA": "period",
    "KW": "period", "BH": "period", "OM": "period", "EG": "period",
    "MA": "comma", "TN": "comma", "DZ": "comma",
    "FR": "comma", "DE": "comma",
    "US": "period", "GB": "period",
}
DEFAULT_DECIMAL_STYLE = "period"


class TenantLocale(NamedTuple):
    country_code: str
    date_day_first: bool
    decimal_style: str
    supported_currencies: List[str]
    preferred_language: str
    primary_currency: str


def resolve_locale(
    country_code: str,
    supported_currencies: Optional[List[str]] = None,
    preferred_language: str = "en",
    primary_currency: str = "",
) -> TenantLocale:
    code = (country_code or "").strip().upper()
    return TenantLocale(
        country_code=code,
        date_day_first=code not in MONTH_FIRST_COUNTRIES,
        decimal_style=COUNTRY_DECIMAL_STYLE.get(code, DEFAULT_DECIMAL_STYLE),
        supported_currencies=supported_currencies or [],
        preferred_language=preferred_language,
        primary_currency=(primary_currency or "").strip().upper(),
    )


def get_tenant_locale(conn, tenant_id: str) -> Optional[TenantLocale]:
    """
    Reads companies.country_code / supported_currencies / preferred_language /
    primary_currency (existing columns) for tenant_id and resolves them into
    a TenantLocale. Returns None if the tenant row is missing or
    soft-deleted, so callers can fall back to the global EXTRACTION_*
    env-var defaults rather than fail outright.

    primary_currency rides along on this same query (rather than a second
    round-trip) because ingestion_pipeline.py needs it for the identical
    reason it needs decimal_style/date_day_first: resolved once per file,
    not per row - see process_records()'s use of it as the fallback
    currency for a source file (e.g. a POS export) whose amounts are
    obviously in the tenant's own home currency but that carries no
    explicit currency column at all.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT country_code, supported_currencies, preferred_language, primary_currency "
            "FROM companies WHERE tenant_id = %s AND deleted_at IS NULL;",
            (tenant_id,),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    country_code, supported_currencies, preferred_language, primary_currency = row
    return resolve_locale(
        country_code, list(supported_currencies or []), preferred_language or "en", primary_currency or "",
    )
