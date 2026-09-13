# POS/ERP Systems We Support — Quick Reference

25 named systems, defined in `src/market_scraper/pos_erp_presets.py` (the source of truth — this
file is a plain-language summary of it, not a separate list). Real vendor names, researched via web
search — see that module's own docstring for research method and limits.

## The two connection mechanisms, simply

- **REST API** — the system has its own web API. A tenant gives us a URL + an access key/token, and
  we pull their data through it on a schedule. This is the easy case.
- **DB Connector** — the system doesn't have a usable API for us. Instead, we get **read-only**
  access to the tenant's own database and pull data with a SQL query. We never write to it.
- **Direct request to vendor** — neither of the above is confirmed to exist yet for this system. Before
  we can connect it at all, someone has to contact the vendor and ask for API access, a webhook, or a
  scheduled data export.

Both real connectors (REST API and DB Connector) already exist and work today:
`POST /onboarding/connect/api` and `POST /onboarding/connect/database`. "Direct request to vendor"
isn't a connector — it's a to-do before one applies.

## Jordan — Pharmacy (3)

| System | Connection |
|---|---|
| Dawatech | Direct request to vendor |
| Smart Pharmacy (Smart Systems) | Direct request to vendor |
| Juleb | Direct request to vendor — **see note below** |

> **Note on Juleb**: real company, but every source we found places it in Saudi Arabia/Gulf
> (Saudi Arabia, Kuwait, Bahrain, Oman, UAE, Qatar), not Jordan. Worth re-confirming directly before
> relying on it as a Jordan pharmacy vendor.

## Jordan — General POS/ERP (9)

| System | Connection |
|---|---|
| GTS One ERP/POS | Direct request to vendor |
| Foodics | REST API |
| Odoo POS/ERP | REST API |
| SAP Business One | REST API |
| Microsoft Dynamics 365 Business Central | REST API |
| Zoho Books/Inventory | REST API |
| Loyverse POS | REST API |
| SAMA POS | Direct request to vendor |
| Square POS | REST API |

## Middle East — Enterprise/Regional ERP (13, plus Foodics and Juleb above which also operate regionally)

| System | Connection |
|---|---|
| SAP S/4HANA | REST API |
| Oracle NetSuite | REST API |
| Oracle Fusion Cloud ERP | REST API |
| IFS Cloud | REST API |
| Microsoft Dynamics 365 (Business Central / F&O) | REST API |
| Odoo | REST API |
| Zoho One/Books | REST API |
| Infor CloudSuite | REST API |
| Epicor Kinetic | REST API |
| Sage 300 / Sage X3 | REST API |
| TallyPrime | DB Connector |
| Wafeq | REST API |
| Focus Softnet ERP | REST API |

## Two things to know before wiring any of these up

1. **No field mappings are built yet.** Knowing "this system has a REST API" is not the same as
   knowing its exact field names. That still has to come from each vendor's real API docs once we
   have an actual account with them — nothing here is guessed at that level.
2. **"25 systems" is a real vendor list, not a market-share ranking.** No published study ranks
   POS/ERP systems by usage in Jordan or the Middle East — we searched and found none. These are
   real, verifiably-operating vendors relevant to each market, not a certified "top 10" / "top 15".
