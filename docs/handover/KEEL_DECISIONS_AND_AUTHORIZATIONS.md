# KEEL — Decisions and Authorizations (2026-11-06)

## Standing safety rules (from `AGENTS.md` and the owner; always apply)
- Never touch 360-Radar or any of its Render services or resources.
- Never commit, print or upload secrets, API keys, tokens or `.env` files.
- No Stripe LIVE operations or real payments. The Stripe Test Clock is local TEST-only and off by default.
- No pushing to main, merging, deploying, force-pushing, resetting Git, or rewriting history without explicit
  owner authorization.
- Commits are authored as Huda Hassouneh with no Claude co-author lines. This applies to main; sessions followed
  it from late October onwards (REPORTED).
- Before any data-changing migration or rollout: make a recoverable backup (a Neon branch) first. Migrations are
  forward-only.
- Report PASS/FAIL/BLOCKED with evidence; never invent results; keep mocked and real-provider tests apart.
- Demo data: one designated synthetic tenant, fictional competitors (VELORA uses `.example` domains), and no
  fabricated AI outputs or payments.

## Decisions taken (REPORTED from sessions; confirm in the commit history where hashes are given)
| Decision | Reason | Evidence |
|---|---|---|
| Production email uses Brevo SMTP port **2525** | Render's free plan blocks 25, 465 and 587 | `dd632af`; Render infra session |
| Production on Render (`ceopro-ai-new`, `keel-web`) with Neon Postgres and the `keelai.net` domain | Chosen deployment target; OCI was evaluated as an alternative | `98c0c53`, `d921681` |
| Production deploys from `claude/vibrant-albattani-j2ksq5`, with main merged in | Set up by the demo-account/deploy session | REPORTED |
| Migrations run without a superuser on managed Postgres 16+ | Neon has no superuser; least privilege | `b21322f` |
| The local LLM question reader stays off in production | 7–15 s latency | `docs/HANDOVER_RAG_JORDANIAN_2026-11-06.md` |
| Sealed evaluation sets stay out of Git | Prevents tuning to the test | same |
| Competition documents are **not** pushed to the public GitHub repo | They name production infrastructure, open credential work and team details | Competition session (owner instruction) |
| VELORA demo uses fictional competitors | No real company is paired with invented prices | `ed5aad0` |
| Approved launch catalog prices published | Billing reconciliation | `b930714`, PR #82 |

## Authorized by the owner
- Pushing the assistant accuracy work to main as Huda Hassouneh (done: `6c9f481` … `33e2d22`).
- The test signup to the owner's Gmail "+keeltest" alias (done).
- Changing `SMTP_PORT` to 2525 and redeploying (done; REPORTED).
- In this session: committing and pushing this handover to `claude/bold-davinci-wy7hdw`.

## Explicitly NOT authorized / still awaiting the owner
- DNS repointing in Cloudflare (pending task 4).
- Pushing the competition documents to GitHub (the owner said no).
- Deleting or force-pushing `claude/busy-cray-u3qw85`.
- Deleting the old Brevo SMTP key.
- The assistant speed/social/research plan, the image-generation port and the forecasting phase.
- Any new receivables/debts data source.
- Render paid-plan spending (B1); DB expiry and admin-credential changes (B2, B3).
- Undoing the two local competition commits (that session offered; the owner did not approve).
- This session's attempt to message other sessions asking them to push their work was **blocked by the permission
  system** for 2 of 3 sessions. Only "KEEL demo account setup" received the request.
