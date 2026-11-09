# Competitor discovery on real data — 2026-11-08

What KEEL's discovery pipeline finds for a real business, measured on real open map data, before and after the
fixes in this change. Nothing here was invented or hand-picked: every business named comes from the
[Overture Maps](https://overturemaps.org/) places dataset, release `2026-10-21.0`, read through KEEL's own
Overture provider (`OVERTURE_EXECUTION=local`, development machine only - never the production API).

## Method

- **Subject:** *Rumi Cafe and Deli*, Jabal Al-Weibdeh, Amman - a real café taken from the dataset itself
  (Overture record `3498cdb1-eb2e-4429-8a8a-f1afe3c1da4d`, 31.95610 N 35.92584 E). Business type "Cafe".
- **Isolation:** a separate company on a disposable local PostgreSQL 17 database, with no products and no
  synthetic records. No production database, account or customer data was read or changed.
- **Pipeline:** the real `pipeline.execute_run` (search, merge, self-exclusion, scoring, classification,
  storage), default radius for cafés (5 km). OpenStreetMap, Nominatim and Wikidata could not be reached from the
  test sandbox and are reported as failed by the run itself; web search and Google Places had no key. Overture
  was therefore the only answering source, so these numbers describe Overture coverage, not every source.
- **Evaluation:** an independent script (not KEEL code) checked the *whole* stored list for the company itself and
  its brand, names that place a business outside food, and one brand listed more than once.

## Results

| | Before | After |
|---|---|---|
| Places read from Overture within 5 km | 572 | 572 |
| Competitors stored (same industry + unverified) | 520 (515 + 5) | 517 (512 + 5) |
| The company itself, incl. its Arabic listing "رومي كيف" | excluded | excluded |
| Name says another trade (medical supplies, a jeweller) | **2** listed | **0** |
| One brand listed twice ("Dimitri's Coffee" and "Dimitri's Coffee - Lweibdeh") | **1** | **0** |
| The company's other location ("Rumi at The Library") | listed | listed - see limits |
| Run time | 18 s | 18 s |

Nearest competitors stored (all within 130 m, as stored distances): Douri, Zokak Coffee House, Macho Cafe,
Dimitri's Coffee - Lweibdeh, Chocoholic Cafe, Tallet Al Weibdeh, Marouf Cafe, Aristotle Cafe, Wildberry,
Reeminikin Cafe, Esquires Coffee House.

## What was fixed (root causes)

1. **A map category overruled the business's own name.** Open map data tags some shops wrongly ("Mandeel for
   medical supplies" as a cafe). `relevance.name_names_another_domain` now lets a name that by itself places a
   business in a different top-level domain (health, retail, electronics vs. food) rule it out. It is deliberately
   coarse: a restaurant-café, an art café or a name the taxonomy cannot place is never dropped.
2. **Missing vocabulary.** `category_taxonomy` had no "medical supplies" entry and no "مقهى" - a company that
   described itself in Arabic as a café got no segment at all.
3. **Branch listings did not merge.** "Brand - Locality", "Brand (Locality)" and "Brand فرع ..." names now share a
   brand key (`matching.brand_key`), guarded so a generic head ("Cafe - Amman") never merges unrelated places.
4. **Sparse areas returned thin lists.** Adaptive radius (`pipeline.search_and_rank`, see
   `docs/ENVIRONMENT_VARIABLES.md`): a default-radius search with too few competitors widens using free sources
   only; an owner-chosen radius is kept and a wider one is offered on the Competitors screen.

## Limits

- **Own branches under a different name** ("Rumi at The Library" for "Rumi Cafe and Deli") stay listed. Matching a
  brand from one shared word is unsafe in Arabic markets, where names such as "Noor" are used by unrelated
  businesses; hiding a real competitor would be worse. The owner removes it with **Reject candidate**.
- **Coffee roasters** (محمص) tagged as cafés stay listed as indirect: they sell coffee, and whether they compete
  with a café is a judgment for the owner.
- With only one answering source, confidence scores are low across the board. On a deployment that can reach
  OpenStreetMap, confidence rises where sources agree.
- Not re-measured on the production API, which does not read Overture itself (see `docs/EXTERNAL_PROCESSOR.md`).

Reproduce: create a company as above on a disposable local database, set `OVERTURE_EXECUTION=local`, and run
`pipeline.execute_run`; list with `discovered_competitors.list_competitors(conn, tenant, limit=5000)`.
