# KEEL — All Sessions Work Inventory (2026-11-06)

Source: `list_sessions` (43 sessions on this account), read by the preservation session at about 20:30 UTC.
"Review depth" says how much of each session was actually read:
- **F**: the final result text was read.
- **S**: only the title and the platform's last summary were read.
- **—**: not reviewed (not a KEEL session).

"Where the work lives" is VERIFIED only where it names a commit on `origin/main` or a remote branch. Anything
described as "local" or "uncommitted" lived in that session's own container. **It is probably already lost** if that
container was reclaimed; older sessions' containers usually are.

## Sessions with work that may exist ONLY outside Git (highest risk)

| Session | Title | What is outside Git | Status |
|---|---|---|---|
| `session_019obuShG5b67AsXmohadjpu` | Competition pitch documentation (F) | `docs/competition/`: the 3 final competition documents (DOCX + PDF) and the PowerPoint review, in local commits `f2b58e83` and `4699907d` on the unpushed branch `claude/funny-wright-wf4cmk` | Kept out of the public repo **at the owner's request**. The files were attached in that session's chat. **Download them there now.** |
| `session_019obuSfWANTCfP7KFZgkzx4` | Model accuracy improvements to 95% (F) | The sealed evaluation sets (deliberately unsaved; only their fingerprints are in `FROZEN_CONFIG.sha256`). All three are spent, so losing them blocks nothing. | Everything else was pushed to main (`6c9f481`, `a5b95f6`, `7962305`, `fc99ae1`, `b8aa514`, `33e2d22`) |
| `session_019obuSiDQdTMDxrwW7z58VV` | KEEL demo account setup (F, partial) | Was merging `b8aa514` and `33e2d22` into `claude/vibrant-albattani-j2ksq5`, then pushing and deploying, at 20:36 UTC. Also had a throwaway test DB. | **Still running.** This session sent it a preservation request (commit and push its own feature branch). Check its chat. |
| `session_019obuSe7cGbE6wwxFs6yAUm` | KEEL AI excellence program (S) | AI quality changes **uncommitted** on `claude/blissful-cannon-vfmyk7`; report `docs/AI_QUALITY_BENCHMARK_REPORT.md` | Branch not on the remote, and the report is not on main. **Probably lost** (Nov 4 container). Later accuracy work on main supersedes most of it. |
| `session_019obuSha4KgQhwrs6fVRdEY` | KEEL AI performance report PDF (S) | `docs/KEEL_AI_PERFORMANCE_REPORT.pdf`, untracked | Not on main. Probably lost; ask that session. |
| `session_019obuSe955mTY6fgBzK7UPX` | KEEL AI accuracy audit (S) | Same PDF, plus benchmark scripts and data, uncommitted | Same as above |
| `session_019obuSfcD15gMrpbJ1FSx7A` | KEEL deployment on Render (S) | Migration patch uncommitted. The fix later landed on main as `b21322f` ("migrations: run on managed Postgres 16+ without a superuser"), which probably supersedes it. | Probably superseded |
| `session_019obuSgHGFyQ65FyeQMb7pu` | CEOPRO-AI technical brief (S) | A rewritten `docs/AI_PROJECT_BRIEF.md`/`.pdf`, uncommitted | An earlier brief is on main (`6d36337`); the rewrite is probably lost |
| `session_019obuSdyMRVCkswscTULDsx` | OCI hosting evaluation (S) | Migration manifest (160 rows) and `compare_neon.py`, in the scratchpad only | Probably lost. It was waiting for the owner's Neon migration list. |

## All other KEEL sessions (newest first)

| Session | Title | Depth | Outcome (REPORTED unless a commit is named) |
|---|---|---|---|
| `session_019obuSe7Jv4h8HjBi449rao` | KEEL demo-account setup | S | Blocked: needs the demo email, full name, business name, country (e.g. JO) and currency (e.g. JOD) |
| `session_019obuSgotFX5iQzn5Y5YnXm` | KEEL international demo readiness | F | Stopped at the 5-hour usage limit (429). Final work state unknown. |
| `session_019obuSeYSG8ZumUWWaQsj5D` | Render infrastructure access setup | F | Diagnosed Render's free-tier SMTP block and proposed port 2525. It was later applied, and docs commit `dd632af` is on main. |
| `session_019obuSe6LsFXJ5N8Vambcc2` | Marketing UI redesign | F | `d1a6eeb` on main. Asks whether to delete or force-push the stale `claude/busy-cray-u3qw85`; **not authorized, leave it** |
| `session_019obuSfEWGrVXu845NrnfRd` | CEOPRO Render migration plan | S | Infrastructure audit and domain plan delivered in chat |
| `session_019obuSe1nGj6nQ5hjcvU1v8` | Render services and deployment audit | S | Deployment plan; decisions B1–B3 (paid/free plan, DB expiry, admin-credential code change) |
| `session_019obuShbyRanfDnHHgXxik8` | Keelai.net domain setup planning | S | Listed the DNS/custom-domain steps (done since; domains are live) |
| `session_019obuSeM2uxbqYLMzYwEKRE` | Render deployment failure fix | S | Asked for a Neon backup branch before migrations |
| `session_019obuSiYWao6eF3HRQ49qdZ` | KEEL Assistant conversational intelligence upgrade | S | Work on main (`1a9108e`); a final choice was left open |
| `session_019obuSgw8ZPRZEPJDRBRxai` | CEOPRO-AI merge conflicts resolution | S | Blocked on a question about PR #80's 6 real billing-UI conflicts; billing reconciliation later merged via PR #82 (`aaa725e`) |
| `session_019obuSeho5p42hAsBdyBzWe` | Subscription pricing UI redesign | S | PR #63 merged; 256 related tests pass |
| `session_019obuSeryyXRpFtMvVGP9us` | Business AI Chatbot question-answering bug | S | `d654389` on main; 464 assistant tests pass |
| `session_019obuSfeFHBdTSciNeXwfm2` | Multi-tenant security test | S | 3-page security PDF delivered in chat, not committed |
| `session_019obuSgnZ823BTZ3vfm2z3f` | Scraping data sources expansion | S | `49eed33` on main; 855 backend and 112 DB tests pass |
| `session_019obuSdvCvMnUP3gGKLYgWF` | Unlimited RAG data retention | S | `15a2596` on main; backend 4,518 pass (35 environment-only fails), frontend 236 pass |
| `session_019obuSeu8i2PV7efBEKvHsE` | CEOPRO-AI full application audit | S | main fast-forwarded `041f9f2`→`0030408`; 3,673 backend tests passed |
| `session_017CmdrDfG341ZtzgyQSRtQu` | Suggestions.MD review | S | Advice only (JSON mode for competitor_analysis) |
| `session_01BgzssJnnoZ4sa3R3iLy6yH` | Business pitfalls and optimization opportunities | S | Merged to main (`b754cbe`) |
| `session_01BDWA5ypADT3yhMk6QLXmTg` | Competitors list provider key error | S | Review-ready; outcome unknown |
| `session_011KEFsmTELiFcKMCujT5U1q` | Sync and merge with CI checks | S | Suggested branch protection for main |
| `session_01MjscJZW4NA9xArUTNyi5Nz` | KEEL autonomous AI setup | S | PR #79 merged (`041f9f2`); user actions listed in `PENDING_ACTIONS.md` |
| `session_01TdwG9QJ4oV2M8rCTofj6v4` | Keel startup process debugging | S | Codespaces port-forward advice |
| `session_016LmpihjpMBXHAFb1LzW56S` | New session | S | Failed |
| `session_01MbpGzn1bXro5UwPuDspUPK` | Groq pricing information | S | Pending, never ran |
| `session_01YHMd1NTDt8C7KM1KPQZjj4` | Sync and pending actions review | S | Asked "what next" |
| `session_01FayKBEfvfXQWEM4h4Pojgs` | KEEL Render staging deployment and billing setup | S | Read-only clone; network blocked |
| `session_01MF8hftXi1AN9S3qL1Kkhou` | RAG system end-to-end in KEEL_Test | S | RAG/research scoping fixes |
| `session_01YYSr6dfTBwkMPvMPXwAB2P` | Keel test branch subscriptions | S | Review-ready |
| `session_01Th8ptu7xyrsr7SaBW8X1xy` | SPIFY data flow investigation | S | Needed Groq/HF keys as Codespaces secrets |
| `session_01PPJTKZuc3yiimVKoDkR8B5` | New session | S | Pending human inputs: rotate exposed keys, Render secrets, 16 migrations, Groq price |
| `session_018TBePb2iY4BTyrJnyGz8md` | New session | S | Compared plan sets in backend vs KEEL_Test |

## Not KEEL (not reviewed, not touched)

- `session_014SdgPJTCP3WX7Wyh8jQsBD`: 360 Radar production-readiness takeover. **Out of scope; never touch 360-Radar.**
- `session_019obuSenfH1Zeq8FigyzohF`: solar assignment (unrelated).
- `session_019obuSftHsrnkKVcCxdj96u`: this preservation session.
