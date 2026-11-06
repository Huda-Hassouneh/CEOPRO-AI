# KEEL — Pending Tasks and Blockers (2026-11-06)

Ordered by urgency. "Owner" means Huda Hassouneh. The owner must approve every production change.

| # | Task | Depends on | Exact next action |
|---|---|---|---|
| 1 | **Save the competition documents** (3 final docs, DOCX + PDF, plus the PowerPoint review) | Session `session_019obuShG5b67AsXmohadjpu` still being reachable | Owner: open "Competition pitch documentation" in the Claude app and download the attachments; keep them privately (Drive). They are deliberately not on GitHub. |
| 2 | Finish the production branch sync and deploy | Session "KEEL demo account setup" (`session_019obuSiDQdTMDxrwW7z58VV`) | Check that `claude/vibrant-albattani-j2ksq5` contains `33e2d22`, and that Render `ceopro-ai-new` is live on it. Its tip was `337561a` at 20:36 UTC. |
| 3 | Decide which single session or person owns production changes | Owner | Owner names one owner. Two agents were deploying at the same time. |
| 4 | **Repoint DNS** away from `keel-frontend-staging`/`keel-ai-staging.onrender.com`, which may be 360-Radar's | Owner approval; confirm the `keel-web` Render hostname | In Cloudflare: `api` → `ceopro-ai-new.onrender.com`; `@` and `www` → the `keel-web` host. Keep grey-cloud CNAMEs as before. Verify the Render custom domains afterwards. |
| 5 | VELORA demo account in production | Owner details: email, full name, business name, country (JO?), currency (JOD?) | Sign up through `https://keelai.net`, verify the emailed code, then seed with `backend/scripts/demo_companies/generate.py --only velora` against **that tenant only**, using the documented seed path. |
| 6 | Finish the test signup and test login and password reset end to end | The code emailed to the owner's Gmail "+keeltest" alias | Enter the code, then log in and run a password reset. Record PASS/FAIL. |
| 7 | Hugging Face token is rejected (401) | Owner: a new HF token; an older proxy rule may take precedence | Replace the HF secret in the environment settings. Then load the embedding model and re-run RAG with embeddings. |
| 8 | Groq key is rejected in the dev environment | Owner key | Measure production answer latency and answer quality (faithfulness, citations). |
| 9 | Raise Jordanian accuracy from 92.3% to 95%+ | A new sealed set, ideally reviewed by a native speaker | Fix the known misses (typos, short product names, «طلبية», competitor vs market); create a new sealed set; score it once. See `docs/HANDOVER_RAG_JORDANIAN_2026-11-06.md`. |
| 10 | Assistant speed, social conversation and research plan | Owner approval, plus items 7 and 8 | Review `docs/ASSISTANT_SPEED_SOCIAL_RESEARCH_PLAN.md` and approve or reject it |
| 11 | Image-generation port; forecasting phase | Owner decisions | Pending decisions, reported by the accuracy session |
| 12 | Delete the old Brevo SMTP key | Owner, in the Brevo dashboard (cannot be undone) | Delete it only once you are comfortable that the new key works (it was REPORTED working) |
| 13 | Rotate the credentials once exposed in Git history | Owner | See `docs/SECURITY_CREDENTIAL_ROTATION.md`. This is still open. |
| 14 | Receivables/debts data for the assistant | Owner approval of a new data source | Design a proposal; nothing has been built |
| 15 | Render free plan limits (SMTP block, sleeping, DB expiry), decisions B1–B3 | Owner cost decision | Decide on the paid or free plan and Neon/DB expiry, and fix the admin-credential handling (B3). |
| 16 | Stale branch `claude/busy-cray-u3qw85` | Owner | Leave as is unless the owner says to delete it. Its content is already on main (`d1a6eeb`). |
| 17 | Lost uncommitted work from Nov 3–4 sessions (AI quality report, performance PDF, OCI manifest, technical-brief rewrite) | Those containers still existing | Open each session; if its files still exist, ask it to deliver them. Otherwise regenerate from main. |
| 18 | Branch protection and CI as required checks on main | Owner, GitHub settings | Enable required PR checks |

## Known limitations (not tasks yet)
- Local test failures come from missing `torch`/`huggingface_hub` and from local-DB integration tests. These failures
  also occur on main before recent commits (REPORTED).
- No native Jordanian speaker has reviewed any evaluation set.
- Production answer speed and quality have not been measured.
