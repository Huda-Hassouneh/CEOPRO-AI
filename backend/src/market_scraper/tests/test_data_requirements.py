"""Keeps the competitor-data setup in one piece, so a missing key or an
unexplained status is caught in CI instead of on the Competitors screen:

- every key, approval and acting-user setting the collectors read is in
  data_requirements.FACETS (so the start-up check warns about it);
- every one is declared where a deployment needs it: render.yaml (API and
  worker), docker-compose.yml (API and enrichment worker), .env.example,
  docs/SECRETS.md and docs/INSTALLATION.md;
- every website-read status and every reason code the backend can send has
  an English and an Arabic sentence and is known to the frontend.
"""
import json
import re
from pathlib import Path

import yaml

from src.market_scraper import competitor_enrichment as ce
from src.market_scraper import data_requirements
from src.market_scraper.market_discovery import intel

BACKEND = Path(__file__).resolve().parents[3]
ROOT = BACKEND.parent
LOCALES = {name: json.loads((ROOT / "frontend/src/assets/locales" / f"{name}.json").read_text(encoding="utf-8"))
           for name in ("en", "ar")}
# Names a collector reads that are something the operator must provide (not a tuning knob).
OPERATOR_PROVIDED = re.compile(r"(_API_KEY|_API_TOKEN|_TOKEN|_APPROVAL_REFERENCE|_ACTOR_USER_ID|_INSTANCE_URL)$")


def _section(locale, path):
    node = LOCALES[locale]
    for part in path.split("."):
        node = node[part]
    return node


def test_every_key_a_collector_reads_is_in_the_requirements_table():
    read = set(re.findall(r'os\.getenv\("([A-Z0-9_]+)"', (BACKEND / "src/market_scraper/competitor_enrichment.py").read_text()))
    provided = {name for name in read if OPERATOR_PROVIDED.search(name)}
    assert provided, "the pattern no longer matches anything: update OPERATOR_PROVIDED"
    assert provided - set(data_requirements.known_names()) == set(), \
        "add these to src/market_scraper/data_requirements.py FACETS"


def test_every_facet_the_ledger_knows_has_a_row():
    facets = {value for name, value in vars(ce).items() if name.startswith("FACET_") and isinstance(value, str)}
    assert facets == set(data_requirements.FACETS)


def test_the_requirements_are_declared_wherever_the_service_is_deployed():
    names = data_requirements.declared_names()
    render_text = (ROOT / "render.yaml").read_text()
    render = yaml.safe_load(render_text)
    api = {v["key"] for v in next(s for s in render["services"] if s["name"] == "keel-ai-staging")["envVars"]}
    # The worker service is commented out in render.yaml until it is paid for; its block must still list them.
    worker = render_text[render_text.index("#    name: keel-workers-staging"):]
    worker_keys = set(re.findall(r"^#\s+- key: ([A-Z0-9_]+)$", worker, re.M))
    compose = yaml.safe_load((BACKEND / "docker-compose.yml").read_text())["services"]
    env_example = (BACKEND / ".env.example").read_text()
    secrets = (ROOT / "docs/SECRETS.md").read_text()
    install = (ROOT / "docs/INSTALLATION.md").read_text()
    gaps = {
        "render.yaml keel-ai-staging": [n for n in names if n not in api],
        "render.yaml keel-workers-staging (commented block)": [n for n in names if n not in worker_keys],
        "docker-compose.yml ai": [n for n in names if n not in compose["ai"]["environment"]],
        "docker-compose.yml market-enrichment-worker": [n for n in names if n not in compose["market-enrichment-worker"]["environment"]],
        ".env.example": [n for n in names if not re.search(rf"^{n}=", env_example, re.M)],
        "docs/SECRETS.md": [n for n in names if f"`{n}`" not in secrets],
        "docs/INSTALLATION.md": [n for n in names if f"`{n}`" not in install],
    }
    assert {where: missing for where, missing in gaps.items() if missing} == {}


def test_every_website_read_status_is_explained_in_both_languages():
    statuses = {value for name, value in vars(intel).items() if name.startswith("STATUS_")}
    for locale in LOCALES:
        assert statuses - set(_section(locale, "intel.status")) == set(), locale
        assert statuses - {intel.STATUS_NO_WEBSITE} - set(_section(locale, "intel.statusShort")) == set(), locale


def test_every_failed_website_read_becomes_a_specific_reason():
    statuses = {value for name, value in vars(intel).items() if name.startswith("STATUS_")}
    unmapped = statuses - {intel.STATUS_PRICES, intel.STATUS_NO_WEBSITE} - set(ce._PRICE_READ_OUTCOMES)  # noqa: SLF001
    assert unmapped == set(), "add them to competitor_enrichment._PRICE_READ_OUTCOMES"


def test_every_reason_code_is_known_to_the_frontend_and_translated():
    source = (BACKEND / "src/market_scraper/competitor_enrichment.py").read_text()
    codes = set(re.findall(r'^([A-Z_]+) = "\1"$', source, re.M))
    frontend = (ROOT / "frontend/src/features/market-intelligence/api/competitorDataApi.js").read_text()
    listed = set(re.findall(r"'([A-Z_]+)'", frontend[frontend.index("export const REASON_CODES"):].split("];")[0]))
    assert codes - listed == set(), "add them to REASON_CODES in competitorDataApi.js (otherwise the owner sees 'unknown')"
    for locale in LOCALES:
        assert codes - set(_section(locale, "competitorData.reason")) == set(), locale


def test_every_reason_code_says_who_acts_next():
    source = (BACKEND / "src/market_scraper/competitor_enrichment.py").read_text()
    codes = set(re.findall(r'^([A-Z_]+) = "\1"$', source, re.M))
    groups = (ce._ADMIN_CODES, ce._WAIT_CODES, ce._OWNER_CODES, ce._NOTHING_TO_DO_CODES, ce._RETRY_CODES)  # noqa: SLF001
    placed = [code for group in groups for code in group]
    assert sorted(placed) == sorted(set(placed)), "a code is in two groups"
    assert codes - set(placed) == set(), "place each code in one group in competitor_enrichment.py (_ADMIN_CODES ...)"


def test_the_website_check_fails_only_when_most_sites_refuse_the_reader(capsys):
    from scripts import website_reader_check

    def collect(answers):
        return lambda url: answers[url]

    refused = {"status": intel.STATUS_REFUSED, "pages_read": [], "http_status": 403}
    read = {"status": intel.STATUS_PRICES, "pages_read": ["https://b.jo"]}
    assert website_reader_check.check(["https://a.jo", "https://c.jo", "https://b.jo"],
                                      collect({"https://a.jo": refused, "https://c.jo": refused, "https://b.jo": read})) == 1
    assert "blocked broadly" in capsys.readouterr().out
    assert website_reader_check.check(["https://a.jo", "https://b.jo"], collect({"https://a.jo": refused, "https://b.jo": read})) == 0
    out = capsys.readouterr().out
    assert "refused_by_site" in out and "403" in out and "https://a.jo" in out
