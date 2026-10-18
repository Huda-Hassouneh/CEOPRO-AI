# Marketing module — two designs, one decision (2026-10-18)

Two independent implementations of the Automated Marketing feature exist.
This is the comparison for `PENDING_ACTIONS.md` #67. Nothing here has been
merged; the older one is kept only as the local ref
`refs/backup/stale-checkout-2026-10-18` in the pre-restructure checkout.

| | **KEEL_Test** (`backend/src/ai/marketing/`) | **Older checkout** (`src/ai/marketing/`) |
|---|---|---|
| Size / tests | ~2,050 lines, 7 unit test files + a live-DB lifecycle test | ~1,700 lines, one `test_marketing.py` |
| Entry point | `routers/marketing.py` (JWT + RLS like every other router) | `api.py` factory mounted from the old single-file `main.py` |
| Campaign inputs | product, free text or URL (`url_extractor`) | uploaded photo + optional prompt |
| Copy | LLM via the shared `llm_client` (`content_generator`) | prompt parser + presets, no LLM copy |
| Grounding | competitor price position, occasions calendar, product history (`positioning`, `occasions`) | none |
| Themes | `creative_direction` (rule-based, traceable to real signals) | `presets` (style / tone / focus) |
| Background removal | `rembg`, provider flag, off by default | `rembg` **or** dependency-free `builtin`, with a confidence value |
| Image | provider-dispatched generation (`image_generation`), reference-image selection | free-provider **pool** with rotation, failover and per-account cooldowns (`ai_image`), local procedural fallback (`scene`) |
| Final ad | the generated image | **Composed ad**: cut-out, shadow, headline, discount badge, CTA, Arabic shaping guard (`composer`) |
| Execution | through the router (not event-driven) | Redis event `campaign_image_requested` + worker (`consumer`), inline fallback |
| Storage | `image_storage` (MinIO) | `storage` (MinIO bucket `ceopro-marketing-assets`) |
| Schema | `20260925*` migrations (`campaign_content`, 3 status facets) | `20261017000000` adds columns to `campaigns` and a status CHECK |

## Recommendation

**Keep KEEL_Test's design as the base.** It is the one wired into auth, RLS,
the shared LLM client and the dashboard signals, and it is the better tested.
Do not merge the older module wholesale: the two define overlapping
`campaigns` columns (`style`, `tone`, `focus`, `error_message`) and the older
migration adds a `chk_campaigns_status` CHECK
(`Pending/Processing/Completed/Failed`) that KEEL_Test's per-facet statuses
were never checked against.

Worth porting **as separate, small PRs** (each needs its own tests on KEEL_Test):
1. `composer.py` — the final ad composition (badge / CTA / headline). KEEL_Test
   stops at the generated image.
2. `ai_image.py` — the provider pool with failover and cooldowns, behind the
   existing `MARKETING_IMAGE_PROVIDER` switch.
3. The `builtin` background remover plus its confidence value, as a fallback
   when `rembg` is off (its default on the free tier).
4. `consumer.py` — only if generation should leave the request path.

Not verified: the older module's own tests were not run against KEEL_Test code.
