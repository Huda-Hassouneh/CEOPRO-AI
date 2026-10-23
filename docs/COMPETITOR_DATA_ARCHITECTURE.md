# Competitor data: how a gap becomes a message, and how to add to it safely

Installation and the checks to run: [INSTALLATION.md](INSTALLATION.md).

## The design rule

Every reason competitor data can be missing is decided **once, on the
server**, as a code, and checked **before** an owner can see it:

1. **At start-up / deploy**, the configuration check names each missing
   setting and the data it blocks.
2. **In CI**, tests fail when the code, the deployment files, the docs and the
   translations disagree.
3. **At run time**, a collector records a specific reason code, never a
   generic failure, and the screen shows that reason and who can act on it.

When something reaches an owner as "not set up" or "an error page", one of
these three layers had a gap. Fix the layer, not only the one occurrence.

## The flow

```
data_requirements.FACETS ──► config_check (API start-up log, ./keel check)
        │                         "YOUTUBE_API_KEY is not set - blocks Video comments"
        │
        ▼ (same settings, read by)
competitor_enrichment.enrich_<facet>()  ──► ledger row (competitor_enrichment table):
   ├─ provider APIs (Places, YouTube,          facet, status, reason_code, reason_detail
   │  Apify, news search)                              │
   └─ intel.collect() ── the competitor's own          ▼
        website: status + HTTP status ──►   next_step_for(reason_code)
        _PRICE_READ_OUTCOMES                  admin | wait | owner | none | retry
                                                       │
                     provider_setup.report_problem ◄───┤ (rejected key / quota: one email a day to OPERATOR_EMAILS)
                                                       ▼
                     API (data_completeness) ──► frontend: REASON_CODES, competitorData.reason.<CODE>
                                                 (en + ar), Retry only when next_step is "retry"
```

| Piece | File | Owns |
|---|---|---|
| Requirements table | `backend/src/market_scraper/data_requirements.py` | which key / approval / setting each facet needs |
| Configuration check | `backend/src/ai/core/config_check.py`, `scripts/check_config.py` | turning missing settings into named warnings |
| Collectors and ledger | `backend/src/market_scraper/competitor_enrichment.py` | reason codes, the next step for each, `_PRICE_READ_OUTCOMES` |
| Website reader | `backend/src/market_scraper/market_discovery/intel.py` | `STATUS_*` for a site read (`refused_by_site`, `http_error`, ...) and the HTTP status |
| Operator screen and alert | `backend/src/market_scraper/provider_setup.py` | *Settings > Service setup*, *Test connection*, the daily email |
| Website check | `backend/scripts/website_reader_check.py` (`./keel site-check`) | can sites be read from this server at all |
| Screen | `frontend/src/features/market-intelligence/` | `REASON_CODES`, `FacetReason`, the Retry button |
| Guard tests | `backend/src/market_scraper/tests/test_data_requirements.py` | that all of the above agree |

## Principles

- **Name the cause, not the symptom.** A firewall's 403 and a broken page
  are different outcomes (`refused_by_site` vs `http_error`), and the HTTP
  status goes into the detail. A new outcome gets its own status rather than
  folding into a generic one.
- **Say who acts.** Each reason code is in exactly one group: admin, wait,
  owner, nothing to do, retry. Owners never get a Retry button for something
  only the operator can fix.
- **Settings live on every service that collects.** The API runs an owner's
  Retry and the worker runs background refreshes; each reads its own
  environment.
- **Respect the site.** robots.txt and a refusal are reported, never worked
  around (no browser impersonation, no proxy rotation).
- **Names, never values.** Checks, logs, alerts and the operator screen say
  whether a key is set, never what it is.

## Adding a provider, setting or outcome: checklist

The guard tests fail until every step is done.

| You add | Also do |
|---|---|
| A key / approval / acting-user setting read by a collector | add it to `data_requirements.FACETS`; declare it in `render.yaml` (API **and** the worker block), `backend/docker-compose.yml` (`ai` **and** `market-enrichment-worker`), `backend/.env.example`, `docs/SECRETS.md` and the table in `docs/INSTALLATION.md` |
| A paid provider | also a `PAID_INTEGRATIONS` row in `config_check.py` and a confirmed price (`scripts.billing_admin set-price`); a test in `provider_setup.py` if operators should be able to test the key |
| A reason code | put it in one group in `competitor_enrichment.py` (`_ADMIN_CODES`, `_WAIT_CODES`, `_OWNER_CODES`, `_NOTHING_TO_DO_CODES`, `_RETRY_CODES`); add it to `REASON_CODES` in `competitorDataApi.js` and to `competitorData.reason` in `en.json` and `ar.json` |
| A website-read status (`intel.STATUS_*`) | map it in `_PRICE_READ_OUTCOMES`; add `intel.status.<status>` and `intel.statusShort.<status>` in `en.json` and `ar.json`; add a row to the troubleshooting table in INSTALLATION.md |
| A facet | a `FACETS` row (even with no needs), plus everything above for its codes |

Then run `./keel check` with the new setting unset (it must name it) and set
(the warning disappears), and `./keel test`.
