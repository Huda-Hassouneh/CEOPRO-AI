"""
CEOPRO AI - Country -> Official Currency Resolution.

Standard ISO 3166-1 alpha-2 (country) -> ISO 4217 (currency) mapping, used
to resolve a tenant's default transaction currency from where the company
is actually located, rather than guessing from the data file itself (a
POS export routinely has no currency column at all - see promotion.py's
own docstring on this, confirmed live against a real 51,947-row file).

This is standard, stable reference data (a country's official currency
changes on the order of decades, not something this session verified
live against a changing API) - unlike e.g. a hosted LLM provider's model
catalog, which genuinely does drift and was verified live elsewhere in
this codebase for exactly that reason.
"""
from typing import Optional

# Common, non-exhaustive: covers the countries this platform's own spec
# names (16-country MENA/regional footprint) plus major global markets.
# A country missing here is not an error - resolve_company_currency()
# below falls back to USD and flags it for human confirmation rather than
# guessing further.
COUNTRY_TO_CURRENCY = {
    "JO": "JOD", "SA": "SAR", "AE": "AED", "EG": "EGP", "QA": "QAR",
    "KW": "KWD", "BH": "BHD", "OM": "OMR", "LB": "LBP", "IQ": "IQD",
    "SY": "SYP", "YE": "YER", "PS": "ILS", "MA": "MAD", "TN": "TND",
    "DZ": "DZD", "LY": "LYD", "SD": "SDG", "TR": "TRY", "IR": "IRR",
    "US": "USD", "CA": "CAD", "GB": "GBP", "IE": "EUR",
    "DE": "EUR", "FR": "EUR", "IT": "EUR", "ES": "EUR", "NL": "EUR",
    "BE": "EUR", "AT": "EUR", "PT": "EUR", "GR": "EUR", "FI": "EUR",
    "CH": "CHF", "SE": "SEK", "NO": "NOK", "DK": "DKK", "PL": "PLN",
    "CZ": "CZK", "HU": "HUF", "RO": "RON",
    "RU": "RUB", "UA": "UAH",
    "CN": "CNY", "JP": "JPY", "KR": "KRW", "IN": "INR", "PK": "PKR",
    "BD": "BDT", "ID": "IDR", "MY": "MYR", "SG": "SGD", "TH": "THB",
    "VN": "VND", "PH": "PHP", "HK": "HKD", "TW": "TWD",
    "AU": "AUD", "NZ": "NZD",
    "BR": "BRL", "MX": "MXN", "AR": "ARS", "CL": "CLP", "CO": "COP",
    "PE": "PEN",
    "ZA": "ZAR", "NG": "NGN", "KE": "KES", "GH": "GHS", "ET": "ETB",
}


def resolve_country_currency(country_code: Optional[str]) -> Optional[str]:
    if not country_code:
        return None
    return COUNTRY_TO_CURRENCY.get(country_code.strip().upper())


def compute_initial_currency(country_code: Optional[str]) -> dict:
    """
    companies.primary_currency is NOT NULL (confirmed live against
    Final_schema.sql - a row cannot exist without one), so there is no
    "backfill a missing value" moment to hook - the derivation has to
    happen once, at the point a company row is first created, computing
    what to insert rather than reading back an empty column that can
    never actually be empty. Order: country_code -> COUNTRY_TO_CURRENCY
    (a real derivation, not a guess) -> 'USD' as the documented last
    resort, flagged needs_confirmation=True so whatever onboarding UI
    creates the row can prompt the user to confirm/correct it - the
    practical equivalent of "ask the user" for a step with no
    interactive prompt available here. The column stays an ordinary,
    already-editable field afterward either way - nothing about this
    locks it.
    """
    currency = resolve_country_currency(country_code)
    if currency:
        return {"currency": currency, "source": "country_lookup", "needs_confirmation": False}
    return {"currency": "USD", "source": "default_fallback", "needs_confirmation": True}


def resolve_company_currency(conn, tenant_id: str) -> dict:
    """
    Reads an existing company's currency. Because primary_currency is
    NOT NULL, this is always just "return what's there" - there is no
    real fallback path to exercise at read time (see
    compute_initial_currency() for where derivation actually happens,
    at row-creation time). A missing company row is the only genuine
    unknown left, and gets the same documented USD/needs_confirmation
    fallback rather than raising.
    """
    with conn.cursor() as cursor:
        cursor.execute("SELECT primary_currency FROM companies WHERE tenant_id = %s;", (tenant_id,))
        row = cursor.fetchone()

    if not row:
        return {"currency": "USD", "source": "no_company_row", "needs_confirmation": True}
    return {"currency": row[0], "source": "primary_currency", "needs_confirmation": False}
