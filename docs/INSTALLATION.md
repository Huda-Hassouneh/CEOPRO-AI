# Installing KEEL and checking it works

The single checklist for a new environment: install, configure, then
**verify before anyone uses it**. Each step links to the detailed guide
instead of repeating it. Run the checks in section 3 after every install and
every change to the service's settings: they catch, in minutes, what a
business owner would otherwise discover on a screen as "not set up" or
"an error page".

| Where | Install guide |
|---|---|
| Your own computer | [RUNNING_LOCALLY.md](../RUNNING_LOCALLY.md) (`./keel setup`, `./keel start`) |
| GitHub Codespaces | [CODESPACES_DEVELOPMENT.md](../CODESPACES_DEVELOPMENT.md) |
| Render staging | [STAGING_DEPLOYMENT.md](../STAGING_DEPLOYMENT.md) (`render.yaml` Blueprint) |

Where each setting is entered (Codespaces secrets, GitHub Actions, the Render
dashboard) and who may hold it: [SECRETS.md](SECRETS.md). How to get each
account and key: [backend/KEYS_AND_ACCOUNTS_NEEDED.md](../backend/KEYS_AND_ACCOUNTS_NEEDED.md).

## 1. Install

Follow the guide for your environment above. When it is done, `./keel status`
(locally) or `GET /health` (staging) answers `ok`.

## 2. Configure, by feature

The core settings (`JWT_SECRET`, `DATABASE_URL`, `APP_DB_PASSWORD`,
addresses, CORS, email, storage) are listed in RUNNING_LOCALLY.md and
STAGING_DEPLOYMENT.md; the configuration check refuses or warns about each.

Competitor data needs the settings below. **Set each one on every service
that collects competitor data**: the API service (`keel-ai-staging`, which
runs an owner's *Retry*) **and** the worker (`keel-workers-staging` /
`market-enrichment-worker`, which runs background refreshes). A setting on
only one of them gives the owner a "not set up" message from the other.

| Competitor data | Settings it needs | Without them the owner sees |
|---|---|---|
| Business profile | `GOOGLE_PLACES_API_KEY` | "A provider key this data needs is not set up on the service." |
| Google reviews | `GOOGLE_PLACES_API_KEY`, `PLACES_TERMS_APPROVAL_REFERENCE`, `SCRAPER_ACTOR_USER_ID` | the key message, then "Storing this data has not been approved by the administrator yet." |
| Video comments | `YOUTUBE_API_KEY`, `EXTERNAL_COMMENTS_APPROVAL_REFERENCE`, `SCRAPER_ACTOR_USER_ID` | the same two messages |
| Social posts and comments | `APIFY_API_TOKEN` (billed per run), `SOCIAL_CONTENT_APPROVAL_REFERENCE` | the same two messages |
| News about them | one of `TAVILY_API_KEY` (free tier), `BRAVE_SEARCH_API_KEY`, `SEARXNG_INSTANCE_URL` | only news from the competitor's own site; the key message when it has none |
| Prices (from their website) | nothing: read directly from the competitor's site | see "Troubleshooting" when sites refuse the reader |
| Social profiles | nothing | |

Also set `OPERATOR_EMAILS` (your address; not a secret). It turns on
**Settings > Service setup**, where an operator sees which of these keys are
set, runs *Test connection*, and receives one email a day when a key is
rejected or its quota is used up.

The three `*_APPROVAL_REFERENCE` settings are not secrets: they name the
ticket or document recording the legal decision to store that data. Paid
providers also need a confirmed price before their calls are allowed
(`python -m scripts.billing_admin set-price`, see
[STAGING_BILLING_RUNBOOK.md](STAGING_BILLING_RUNBOOK.md)).

This table is enforced: `backend/src/market_scraper/data_requirements.py`
holds the same list in code, and a test fails if a setting the collectors
read is missing from it, from `render.yaml`, `docker-compose.yml`,
`.env.example`, SECRETS.md or this page.

## 3. Verify (before anyone uses it)

Run these in order. Each prints setting **names** and problems, never a value.

| # | Check | Command | Passes when |
|---|---|---|---|
| 1 | Settings | `./keel check` (or, on the server, `cd backend && python -m scripts.check_config --db`) | `0 error(s)`. Every warning names the setting and the feature it blocks, e.g. *"YOUTUBE_API_KEY: is not set ... blocks Video comments for every company"*. The API also logs these lines at start-up: read them in the Render log after each deploy. |
| 2 | Provider keys really work | **Settings > Service setup > Test connection** for each provider (needs `OPERATOR_EMAILS`) | every configured provider answers *valid* |
| 3 | AI model | `./keel llm-check` | the provider, price and model are confirmed |
| 4 | Competitor websites can be read **from the server** | `./keel site-check https://<a-competitor-site> ...`, or on the server `cd backend && python -m scripts.website_reader_check --db` | exit code 0. It fails when more than half of the sites refuse the reader (see Troubleshooting). Run it where the service runs: sites block by address, so a laptop's result says nothing about Render's. |
| 5 | One competitor end to end | track one real competitor, press **Retry**, open **Why missing** | each data type is *Collected*, or its reason names something you chose not to set up |
| 6 | Assistant | `./keel rag-check` | cited answers in English and Arabic |

Render's free plan has no shell. There, check 1 is the start-up log, and
check 4 is check 5: the website read's detail names the HTTP status it got,
e.g. *"The website's firewall or bot protection turned the reader away (HTTP 403)."*

## 4. Troubleshooting: message → cause → fix

| The owner sees | Cause | Fix |
|---|---|---|
| "A provider key this data needs is not set up on the service." | The key for that data type is not set on the service that ran it (section 2) | Set it on **both** the API and the worker; `./keel check` names it. Retrying doesn't help, which is why that data type shows no Retry button |
| "Storing this data has not been approved by the administrator yet." | The `*_APPROVAL_REFERENCE` for that data type is empty | Record the legal decision, then set the reference |
| "The service is missing a setting. Please contact support." | `SCRAPER_ACTOR_USER_ID` is missing for background collection | Set it (render.yaml sets the built-in service identity) |
| "Google rejected the key..." / an operator email "... needs attention" | Key revoked, restricted to the wrong API, or billing off | Fix it in the provider console, then *Test connection* |
| "Their website's firewall or bot protection turned KEEL away..." | The competitor's site answers 401/403/429 (or a Cloudflare challenge) to automated readers | Nothing to fix on one site: KEEL respects it and does not try to get around it. If `site-check` shows **most** sites refusing, the server's address or `MARKET_RESEARCH_USER_AGENT` is being blocked broadly: check the User-Agent identifies KEEL with a contact address, or move the collector to another egress |
| "Their website answered with an error page." | A real error (404, 5xx, or a non-HTML answer); the detail names the HTTP status | Check the competitor's website address on its profile; a 5xx is retried automatically |
| "Their website asks automated readers not to read these pages" | The site's robots.txt disallows it | Nothing: respected by design |
| A Retry that never finishes in the background | No worker is running | Start it (`./keel workers`; on Render the worker needs a paid plan, see STAGING_DEPLOYMENT.md) |

How these messages are produced, and the rules for adding a new provider or
outcome without reintroducing these problems:
[COMPETITOR_DATA_ARCHITECTURE.md](COMPETITOR_DATA_ARCHITECTURE.md).
