"""
Named POS/ERP vendor presets for onboarding - real vendor names and how a
tenant using each one would actually connect, wired onto the two connectors
this repo already has (api_connector_sync.py for a REST API, connector_sync.py
for direct database access). No vendor-specific fetch code lives here: each
preset is metadata (who the vendor is, whether they're confirmed operating
in this market, and which of the two existing connectors realistically
fits them) plus a config *template* for `POST /onboarding/connect/api` or
`/connect/database` - the real base_url/host/field_mapping/credentials
still have to come from that vendor's own account/API docs, which this
codebase has no access to. Nothing here is guessed at the field-name level;
see `resolve_preset()`'s own docstring for exactly what is and isn't filled in.

Research basis (web search, 2026-09-13) and its limits:
- Vendor identities, HQ country, and which countries each is confirmed to
  operate in come from that vendor's own site or a business-data source
  (CB Insights, RocketReach) found via search this session - cited per
  entry below.
- There is no independently-published, market-share-ranked "top 10 in
  Jordan" or "top 15 in the Middle East" study for POS/ERP vendors (unlike,
  say, an analyst report ranking global cloud providers) - a request for
  one was searched for and none was found. What follows instead is a list
  of real, verifiably-operating vendors relevant to each market, grouped by
  category, NOT a claim that this is the definitive top-N by installed base
  or revenue. Flag this to whoever consumes it rather than presenting a
  precision this data doesn't have.
- A few enterprise ERP entries (Infor, Epicor, Sage, Tally, Wafeq, Focus
  Softnet) are included on general industry knowledge of long-established
  Middle East ERP vendors rather than a live search result confirming each
  one specifically this session - marked `verified_live=False` below,
  distinct from every other entry (`verified_live=True`) that came from an
  actual search result fetched this session.
"""
from typing import Optional

# ---------------------------------------------------------------------------
# Connection mechanisms
# ---------------------------------------------------------------------------
# "generic_api" - vendor has (or plausibly could grant) a REST/OData API a
#   tenant's own account can authenticate against; wire it up via the
#   existing api_connector_sync.py / POST /onboarding/connect/api, once the
#   tenant supplies their own base_url + auth + the vendor's real field
#   names in field_mapping.
# "generic_database" - vendor is typically a single-tenant/on-prem
#   deployment with a conventional SQL backend; the realistic path is the
#   tenant granting this app read-only DB access, via the existing
#   connector_sync.py / POST /onboarding/connect/database.
# "vendor_direct_request" - no public self-serve API is confirmed to exist;
#   connecting requires the tenant (or us, on their behalf) contacting the
#   vendor's own business/support team to request either API/webhook access
#   or a scheduled data export, before either generic connector applies.
CONNECTION_MECHANISMS = ("generic_api", "generic_database", "vendor_direct_request")


def _preset(
    display_name: str, vendor_of: str, category: str, hq_country: str,
    confirmed_countries: tuple, connection_mechanism: str, mechanism_note: str,
    source_note: str, verified_live: bool = True,
) -> dict:
    if connection_mechanism not in CONNECTION_MECHANISMS:
        raise ValueError(f"unknown connection_mechanism: {connection_mechanism!r}")
    return {
        "display_name": display_name, "vendor_of": vendor_of, "category": category,
        "hq_country": hq_country, "confirmed_countries": confirmed_countries,
        "connection_mechanism": connection_mechanism, "mechanism_note": mechanism_note,
        "source_note": source_note, "verified_live": verified_live,
    }


# ---------------------------------------------------------------------------
# Jordan - pharmacy POS/ERP (the user's own top-3 candidates)
# ---------------------------------------------------------------------------
JORDAN_PHARMACY_PRESETS = {
    "dawatech": _preset(
        display_name="Dawatech", vendor_of="Dawatech (est. 2020, Amman)",
        category="pharmacy_pos", hq_country="Jordan", confirmed_countries=("Jordan",),
        connection_mechanism="vendor_direct_request",
        mechanism_note=(
            "Cloud SaaS pharmacy ERP (POS, accounting, inventory, CRM modules). No "
            "public self-serve API docs were found - request API/webhook access "
            "directly from Dawatech, or fall back to generic_database if they'll "
            "grant read-only access to a tenant's own data instead."
        ),
        source_note="dawatech.com/modules, dawatech.com; confirmed Amman, Jordan HQ, founded 2020 (cbinsights.com/company/dawatech).",
    ),
    "smart_systems": _preset(
        display_name="Smart Pharmacy (Smart Systems)", vendor_of="Smart Systems (Amman)",
        category="pharmacy_pos", hq_country="Jordan",
        confirmed_countries=("Jordan", "Saudi Arabia", "United Arab Emirates", "Palestine"),
        connection_mechanism="vendor_direct_request",
        mechanism_note=(
            "On-prem/desktop-oriented suite (Smart Pharmacy, Smart POS, Smart "
            "Accounting are separate modules from the same vendor). No public API "
            "confirmed - the realistic path for an on-prem deployment is "
            "generic_database (read-only access to the client's own local database) "
            "once Smart Systems or the tenant confirms which DB engine it runs on."
        ),
        source_note="smartsoft-sys.com; Amman, Jordan HQ, product line includes Smart Pharmacy/Smart POS/Smart Accounting.",
    ),
    "juleb": _preset(
        display_name="Juleb", vendor_of="Juleb (formerly Al-Dawaa, est. 2017, Jeddah)",
        category="pharmacy_pos", hq_country="Saudi Arabia",
        confirmed_countries=("Saudi Arabia", "Kuwait", "Bahrain", "Oman", "United Arab Emirates", "Qatar"),
        connection_mechanism="vendor_direct_request",
        mechanism_note=(
            "IMPORTANT DISCREPANCY: search sources describe Juleb as Jeddah, Saudi "
            "Arabia-headquartered, serving 700+ pharmacy branches across Saudi "
            "Arabia/Kuwait/Bahrain/Oman/UAE/Qatar - Jordan was not named as one of "
            "its confirmed markets in the sources checked. Included here as "
            "requested, but this should be re-confirmed directly with Juleb (or "
            "with the specific Jordan pharmacy chain using it) before treating it "
            "as a Jordan pharmacy vendor. No public API confirmed either way."
        ),
        source_note="juleb.com, cbinsights.com/company/juleb, saudigazette.com.sa/article/647523; Jordan presence not found in these sources.",
        verified_live=True,
    ),
}

# ---------------------------------------------------------------------------
# Jordan - general POS/ERP (retail-wide, not pharmacy-specific)
# ---------------------------------------------------------------------------
JORDAN_GENERAL_PRESETS = {
    "gts_one": _preset(
        display_name="GTS One ERP/POS", vendor_of="GTS (gtsys.com.jo, Amman)",
        category="general_pos", hq_country="Jordan", confirmed_countries=("Jordan",),
        connection_mechanism="vendor_direct_request",
        mechanism_note="Jordan-based ERP/POS/CRM vendor (restaurant + retail billing). No public API confirmed.",
        source_note="gtsys.com.jo",
    ),
    "foodics": _preset(
        display_name="Foodics", vendor_of="Foodics (Riyadh, Saudi Arabia)",
        category="general_pos", hq_country="Saudi Arabia",
        confirmed_countries=("Saudi Arabia", "Egypt", "United Arab Emirates", "Kuwait", "Jordan"),
        connection_mechanism="generic_api",
        mechanism_note=(
            "Foodics publishes its own public REST API/webhooks for connected apps "
            "- once a tenant grants API access from their own Foodics account, this "
            "is a real generic_api fit (base_url + Foodics' own field names in "
            "field_mapping, confirmed against Foodics' developer docs, not guessed here)."
        ),
        source_note="confirmed active client base in Jordan per search results (growing presence across Saudi Arabia, Egypt, UAE, Kuwait, Jordan).",
    ),
    "odoo": _preset(
        display_name="Odoo POS/ERP", vendor_of="Odoo S.A. (Belgium; regionally resold by Jordan partners e.g. Pinnacle Innovation)",
        category="general_pos", hq_country="Belgium", confirmed_countries=("Jordan",),
        connection_mechanism="generic_api",
        mechanism_note="Odoo exposes XML-RPC/JSON-RPC (and REST via community modules) - fits generic_api once auth + field_mapping are confirmed for the tenant's own Odoo instance.",
        source_note="jordancomputers.com/en/pos-software-en lists Odoo POS as offered in Jordan; pijordan.com (Pinnacle Innovation) is a Jordan-based Odoo reseller.",
    ),
    "sap_business_one": _preset(
        display_name="SAP Business One", vendor_of="SAP SE (regionally resold by Jordan partners e.g. Advanced Business Solutions, SkyTech)",
        category="enterprise_erp", hq_country="Germany", confirmed_countries=("Jordan",),
        connection_mechanism="generic_api",
        mechanism_note="SAP Business One exposes the Service Layer, a documented OData/REST API - fits generic_api once the tenant's own Service Layer URL and credentials are supplied.",
        source_note="e2abs.com (Advanced Business Solutions, Jordan SAP partner), e-skytech.com (SkyTech, Jordan SAP Business One/Odoo/Dynamics partner).",
    ),
    "dynamics_365_bc": _preset(
        display_name="Microsoft Dynamics 365 Business Central", vendor_of="Microsoft (regionally resold by Jordan partners e.g. INSIGHT Business Solutions, SkyTech)",
        category="enterprise_erp", hq_country="United States", confirmed_countries=("Jordan",),
        connection_mechanism="generic_api",
        mechanism_note="Business Central exposes a documented OData v4 API - fits generic_api once the tenant's own environment URL and OAuth credentials are supplied.",
        source_note="insight-jo.com (INSIGHT Business Solutions, Jordan Microsoft Dynamics Gold Partner).",
    ),
    "zoho": _preset(
        display_name="Zoho Books/Inventory", vendor_of="Zoho Corporation (regionally resold by Jordan partners e.g. SkyTech)",
        category="general_pos", hq_country="India", confirmed_countries=("Jordan",),
        connection_mechanism="generic_api",
        mechanism_note="Zoho publishes a documented REST API - fits generic_api once the tenant's own Zoho account API key/OAuth token and field_mapping are supplied.",
        source_note="e-skytech.com lists Zoho among the ERPs it implements in Jordan.",
    ),
    "loyverse": _preset(
        display_name="Loyverse POS", vendor_of="Loyverse (Kyiv, Ukraine)",
        category="general_pos", hq_country="Ukraine", confirmed_countries=("Jordan",),
        connection_mechanism="generic_api",
        mechanism_note="Loyverse publishes a documented public REST API - fits generic_api once the tenant's own API token and field_mapping are supplied.",
        source_note="jordancomputers.com/en/pos-software-en lists Loyverse POS as offered/sold in Jordan.",
    ),
    "sama_pos": _preset(
        display_name="SAMA POS", vendor_of="SAMA POS (Cairo, Egypt)",
        category="general_pos", hq_country="Egypt", confirmed_countries=("Jordan",),
        connection_mechanism="vendor_direct_request",
        mechanism_note="No public self-serve API confirmed in the sources checked - request API access directly from SAMA POS.",
        source_note="jordancomputers.com/en/pos-software-en lists Sama POS as offered/sold in Jordan.",
    ),
    "square": _preset(
        display_name="Square POS", vendor_of="Block, Inc. (San Francisco, USA)",
        category="general_pos", hq_country="United States", confirmed_countries=("Jordan",),
        connection_mechanism="generic_api",
        mechanism_note="Square publishes a documented public REST API - fits generic_api once the tenant's own access token and field_mapping are supplied.",
        source_note="jordancomputers.com/en/pos-software-en lists Square POS as offered/sold in Jordan.",
    ),
}

# ---------------------------------------------------------------------------
# Middle East - enterprise/regional ERP (broader than Jordan alone)
# ---------------------------------------------------------------------------
MIDDLE_EAST_PRESETS = {
    "sap_s4hana": _preset(
        display_name="SAP S/4HANA", vendor_of="SAP SE", category="enterprise_erp",
        hq_country="Germany", confirmed_countries=("United Arab Emirates", "Saudi Arabia"),
        connection_mechanism="generic_api",
        mechanism_note="OData-based APIs (SAP Gateway / Service Layer for the SMB SAP Business One line) - generic_api once the tenant's own endpoint and credentials are supplied.",
        source_note="most-deployed enterprise ERP in the UAE by installation count per search results; enterprise-tier standard across PIF subsidiaries, banks, airlines per Saudi ERP market search.",
    ),
    "oracle_netsuite": _preset(
        display_name="Oracle NetSuite", vendor_of="Oracle Corporation", category="enterprise_erp",
        hq_country="United States", confirmed_countries=("United Arab Emirates", "Saudi Arabia"),
        connection_mechanism="generic_api",
        mechanism_note="NetSuite's SuiteTalk REST/SOAP API - generic_api once the tenant's own account ID and OAuth/token credentials are supplied.",
        source_note="leads the Middle East ERP mid-market segment per search results; anchors real-estate/contracting/giga-project supply-chain adoption in Saudi Arabia.",
    ),
    "oracle_fusion_cloud": _preset(
        display_name="Oracle Fusion Cloud ERP", vendor_of="Oracle Corporation", category="enterprise_erp",
        hq_country="United States", confirmed_countries=("Saudi Arabia",),
        connection_mechanism="generic_api",
        mechanism_note="Documented REST API - generic_api once the tenant's own environment and credentials are supplied.",
        source_note="named alongside SAP S/4HANA and IFS as the enterprise-tier standard for PIF subsidiaries/banks/airlines/government per search results.",
    ),
    "ifs": _preset(
        display_name="IFS Cloud", vendor_of="IFS AB", category="enterprise_erp",
        hq_country="Sweden", confirmed_countries=("Saudi Arabia",),
        connection_mechanism="generic_api",
        mechanism_note="Documented REST/OData API (IFS Connect) - generic_api once the tenant's own endpoint and credentials are supplied.",
        source_note="named among the three enterprise-tier ERPs (with SAP S/4HANA and Oracle Fusion Cloud) for PIF subsidiaries/banks/airlines/government per search results.",
    ),
    "dynamics_365": _preset(
        display_name="Microsoft Dynamics 365 (Business Central / F&O)", vendor_of="Microsoft",
        category="enterprise_erp", hq_country="United States",
        confirmed_countries=("United Arab Emirates", "Saudi Arabia", "Jordan"),
        connection_mechanism="generic_api",
        mechanism_note="Documented OData v4 API - generic_api once the tenant's own environment and OAuth credentials are supplied.",
        source_note="named as the mid-market/growth-stage choice for organizations already on Microsoft technology per search results.",
    ),
    "odoo_regional": _preset(
        display_name="Odoo", vendor_of="Odoo S.A.", category="enterprise_erp",
        hq_country="Belgium", confirmed_countries=("United Arab Emirates", "Saudi Arabia", "Jordan"),
        connection_mechanism="generic_api",
        mechanism_note="XML-RPC/JSON-RPC (or REST via community modules) - generic_api once the tenant's own instance and credentials are supplied.",
        source_note="named as the flexible/customizable choice for growing mid-market companies per search results.",
    ),
    "foodics_regional": _preset(
        display_name="Foodics", vendor_of="Foodics", category="general_pos",
        hq_country="Saudi Arabia",
        confirmed_countries=("Saudi Arabia", "Egypt", "United Arab Emirates", "Kuwait", "Jordan"),
        connection_mechanism="generic_api",
        mechanism_note="Publishes its own public REST API/webhooks - generic_api once the tenant grants API access from their own account.",
        source_note="see JORDAN_GENERAL_PRESETS['foodics'] - same vendor, regional footprint.",
    ),
    "juleb_regional": _preset(
        display_name="Juleb", vendor_of="Juleb", category="pharmacy_pos",
        hq_country="Saudi Arabia",
        confirmed_countries=("Saudi Arabia", "Kuwait", "Bahrain", "Oman", "United Arab Emirates", "Qatar"),
        connection_mechanism="vendor_direct_request",
        mechanism_note="See JORDAN_PHARMACY_PRESETS['juleb'] for the Jordan-presence discrepancy - no public API confirmed.",
        source_note="700+ pharmacy branches across Saudi Arabia/Kuwait/Bahrain/Oman/UAE/Qatar per search results.",
    ),
    "zoho_regional": _preset(
        display_name="Zoho One/Books", vendor_of="Zoho Corporation", category="general_pos",
        hq_country="India", confirmed_countries=("United Arab Emirates", "Saudi Arabia", "Jordan"),
        connection_mechanism="generic_api",
        mechanism_note="Documented REST API - generic_api once the tenant's own API key/OAuth token is supplied.",
        source_note="see JORDAN_GENERAL_PRESETS['zoho'].",
    ),
    "infor": _preset(
        display_name="Infor CloudSuite", vendor_of="Infor", category="enterprise_erp",
        hq_country="United States", confirmed_countries=(),
        connection_mechanism="generic_api",
        mechanism_note="Documented REST API (Infor OS/ION API) - generic_api once the tenant's own tenant ID and credentials are supplied.",
        source_note="established global enterprise ERP vendor with a long-standing Middle East presence - general industry knowledge, not independently re-verified via live search this session.",
        verified_live=False,
    ),
    "epicor": _preset(
        display_name="Epicor Kinetic", vendor_of="Epicor Software Corporation", category="enterprise_erp",
        hq_country="United States", confirmed_countries=(),
        connection_mechanism="generic_api",
        mechanism_note="Documented REST API - generic_api once the tenant's own environment and credentials are supplied.",
        source_note="established global manufacturing-sector ERP vendor with a Middle East presence - general industry knowledge, not independently re-verified via live search this session.",
        verified_live=False,
    ),
    "sage": _preset(
        display_name="Sage 300 / Sage X3", vendor_of="The Sage Group plc", category="enterprise_erp",
        hq_country="United Kingdom", confirmed_countries=(),
        connection_mechanism="generic_api",
        mechanism_note="Documented REST/OData API - generic_api once the tenant's own environment and credentials are supplied.",
        source_note="established SME/mid-market ERP vendor long active in the GCC - general industry knowledge, not independently re-verified via live search this session.",
        verified_live=False,
    ),
    "tally": _preset(
        display_name="TallyPrime", vendor_of="Tally Solutions", category="general_pos",
        hq_country="India", confirmed_countries=(),
        connection_mechanism="generic_database",
        mechanism_note="Primarily an on-prem/desktop accounting package - the realistic path is generic_database (read-only access to the tenant's own local Tally data) rather than a public API.",
        source_note="widely used by South Asian-expatriate-run SMEs across the Gulf - general industry knowledge, not independently re-verified via live search this session.",
        verified_live=False,
    ),
    "wafeq": _preset(
        display_name="Wafeq", vendor_of="Wafeq", category="general_pos",
        hq_country="Egypt", confirmed_countries=(),
        connection_mechanism="generic_api",
        mechanism_note="Cloud accounting platform with a documented REST API - generic_api once the tenant's own API key is supplied.",
        source_note="MENA-native cloud accounting/ERP-lite platform gaining SME traction - general industry knowledge, not independently re-verified via live search this session.",
        verified_live=False,
    ),
    "focus_softnet": _preset(
        display_name="Focus Softnet ERP", vendor_of="Focus Softnet", category="enterprise_erp",
        hq_country="United Arab Emirates", confirmed_countries=(),
        connection_mechanism="generic_api",
        mechanism_note="Documented REST API - generic_api once the tenant's own environment and credentials are supplied.",
        source_note="Dubai-headquartered ERP vendor long established in the GCC SME market - general industry knowledge, not independently re-verified via live search this session.",
        verified_live=False,
    ),
}

ALL_PRESETS = {**JORDAN_PHARMACY_PRESETS, **JORDAN_GENERAL_PRESETS, **MIDDLE_EAST_PRESETS}


def resolve_preset(vendor_slug: str) -> Optional[dict]:
    """Look up a vendor preset by slug (see the module-level dicts above)."""
    return ALL_PRESETS.get(vendor_slug)


def onboarding_connector_hint(vendor_slug: str) -> dict:
    """
    Translates a preset's connection_mechanism into which existing
    onboarding endpoint applies and what a tenant still has to supply -
    never a filled-in field_mapping, since this codebase has no confirmed
    field-level schema for any of these vendors' own APIs/databases.
    """
    preset = resolve_preset(vendor_slug)
    if preset is None:
        raise KeyError(f"no preset registered for vendor_slug: {vendor_slug!r}")
    if preset["connection_mechanism"] == "generic_api":
        return {
            "endpoint": "POST /onboarding/connect/api",
            "required_from_tenant": ["base_url", "field_mapping", "credentials (auth per vendor's own API docs)"],
            "note": preset["mechanism_note"],
        }
    if preset["connection_mechanism"] == "generic_database":
        return {
            "endpoint": "POST /onboarding/connect/database",
            "required_from_tenant": ["host", "port", "dbname", "query", "field_mapping", "credentials"],
            "note": preset["mechanism_note"],
        }
    return {
        "endpoint": None,
        "required_from_tenant": ["direct confirmation from the vendor of an API/webhook/export option"],
        "note": preset["mechanism_note"],
    }
