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

## Second business type: a pharmacy — 2026-11-09

Same method, same Overture release, to check that the relevance rules hold beyond cafés.

- **Subject:** *Tala Alfarkh Pharmacy*, Al-Abdali, Amman (Overture `8d42a1e3-ba04-4f03-92f9-285aa10c6169`,
  31.95397 N 35.91121 E). Business type "Pharmacy", industry `pharmacy`, default radius 5 km, no products.
- **Code measured:** `main` + #104 + #105 ("before") and the same plus this change ("after"), each on a disposable
  local PostgreSQL 17 database with an otherwise empty company. Only Overture answered (same blocked sources as above).
- **Evaluation:** every name of the before-list was read by hand; 30 were labelled as clearly another health trade
  (clinics, medical-equipment and supply dealers, an optician, dental labs, a "clinic for rent"). Ambiguous names
  (drug warehouses, a veterinary pharmacy, "medical services") were not labelled and are not counted either way.

| | Before | After |
|---|---|---|
| Places read from Overture within 5 km | 285 | 285 |
| Competitors stored | 265 | 240 |
| The company itself | excluded | excluded |
| Labelled other health trades listed | **30** | **4** |
| ... among the 10 auto-tracked | **4** ("clinic for rent", a nuclear-medicine centre, 2 equipment dealers) | **0** |
| Real pharmacies removed | - | **0** (every removed name was labelled) |
| Pharmacies typed as something else (spa) now kept | - | 1 ("Al Bisher Pharmacy") |
| Run time | 15 s | 16 s |

Café re-run (Rumi Cafe and Deli) on the same two trees: nothing removed, no relationship changed, and 2 cafés whose
map type was wrong ("كافيه الجادور" typed burger restaurant, "الباشا كافيه" typed grocery store) are now kept.

### Root causes fixed

1. **Health trades were too shallow in the taxonomy.** Every health leaf had a 2-level path, so any two health
   businesses scored 0.5 - exactly the competing bar - and a medical-equipment dealer counted as a pharmacy's rival.
   Other health trades now sit one level deeper (`health > equipment > medical supplies`, `health > care > clinic`,
   `health > care > dental`, `health > optics > eyewear`), 0.33 against a pharmacy. The pharmacy path, already
   stored on competitors (`global_competitors.category_path`), is unchanged.
2. **The map type always outweighed the name inside one domain.** `relevance.in_different_category` now (a) keeps a
   listing whose own name says the company's trade, whatever its type, and (b) lets a name in an unambiguous trade
   (`category_taxonomy.NAME_DECISIVE_PATHS`) outweigh the type. The new leaves carry no map types: real pharmacies
   are also typed "hospital" in the data, and the deepest type would otherwise win.
3. **Arabic names did not match.** "للأجهزة الطبية" never matched "أجهزة طبية". Names and keywords are now folded the
   same way (alef/ta-marbuta/ya variants, short vowels, the article and its ل/و/ب/ف/ك prefixes).

### Limits (pharmacy)

- **Same industry without a specialty → `DIRECT` (owner decision, 2026-11-09).** Before, DIRECT needed evidence of the
  company's specialty, so a company with no products got no direct competitors at all (pharmacy: 0 of 240). Now, when
  the owner has given no products and no specialty words in the business type, a business of the same industry is
  DIRECT by default (reason `same_industry_default`, shown in EN/AR). With products or a specialty the owner wrote,
  the conservative rule stays. A default DIRECT is not evidence: it still has to be in the company's segment.
  Re-run on the same data: pharmacy 191 DIRECT / 39 INDIRECT / 10 unverified (was 0 / 230 / 10), café 450 / 64 / 5
  (was 0 / 514 / 5); the stored lists, the auto-tracked ten and the 4 remaining off-trade names are identical. The
  39 still INDIRECT are named like pharmacies but typed otherwise (23 "health care", 3 "pharmaceutical company"):
  the map does not confirm the industry, so they keep the conservative label.
- 4 labelled names remain: a typo ("Biel Medical Supplie"), and names with no trade word ("MicroDent MENA",
  "Medical Life Solution industrial Company", "الكاملة للتكنولوجيا"). Reject candidate removes them.
- Spelling variants of one brand at different addresses ("Salma Al Qosous" / "Salma Qsous", "Adam & Taym" / "Adam and
  taim") are listed separately; merging transliterations is unsafe for the same reason as single shared words.
- Drug warehouses (مستودع أدوية, often B2B wholesalers) stay listed: some sell to the public.
