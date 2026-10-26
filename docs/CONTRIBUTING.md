# Contributing

1. Read the root Quick Start and the relevant domain guide.
2. Preserve unrelated changes. Work on a scoped branch/worktree; never reset another developer's checkout.
3. Reuse existing Python authorities and React design/components.
4. Add the smallest regression test for changed behavior.
5. Run tooling tests for launch changes; frontend tests/lint/build for UI changes; native database/security tests for schema/role changes.
6. Commit source/tests/docs explicitly. Review `git diff --cached` and `git status` before committing.

## Important boundaries

- No Node runtime billing/identity service or duplicate credit/catalog authority.
- Do not change AI model mathematics to repair an adapter.
- Tenant scope and Platform Owner checks must be enforced in Python, not just navigation.
- Applied SQL migrations are immutable. Add uniquely ordered forward migrations and test upgrade/repeat behavior.
- Never use superuser application connections to pass a test.
- Do not invent provider prices, financial policy or discount/transition rules.
- Keep provider fixtures clearly synthetic. Fixture tests are not real merchant/Stripe acceptance.
- Preserve English/Arabic translation keys, accessible labels and RTL behavior.
- Never commit `.env`, `.dev/`, credentials, dumps, local logs or model caches.

## Verification

`dev.ps1 test` runs tooling tests only. Use `--suite frontend` for React tests/lint/build and `--suite database` for the local isolated migration/RLS journey. Select affected Python modules directly using the environment pattern in LOCAL_DEVELOPMENT.

Browser tests require an installed Chromium and explicit synthetic identities. Do not run broad browser suites that create quotes, payments or provider records without understanding their mutation scope.

Keep current contributor guidance under `docs/`. Preserve historical evidence in `docs/keel-integration/`; date new evidence and distinguish PASS/FAIL/BLOCKED/UNRUN. Update the environment inventory after adding settings.

Local development tooling does not authorize a remote push, protected-main merge, production change or deployment.
