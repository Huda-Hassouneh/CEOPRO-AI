# Demo / acceptance companies

Seven realistic companies used to validate KEEL end to end across very
different businesses. The application never reads this folder; it exists so
anyone can recreate the same data on any deployment through the public API.

| Key | Company | Country / currency | Business | Sales export format |
|---|---|---|---|---|
| zaytouna | Zaytouna Fine Foods | JO / JOD (3 decimals) | Specialty grocery, 2 stores + online | English CSV, quarterly, ~50k lines |
| atlas | Atlas Couture | MA / MAD | Fashion boutique (size variants, alterations service) | French CSV, `;` separator, comma decimals |
| beit | Beit Al Shawarma | AE / AED | Restaurant (menu items, grill sold per kg) | Arabic Excel daily item report, monthly |
| nour | Nour Beauty Lounge | SA / SAR | Salon services (no stock) + retail products | Arabic CSV in Windows-1256 |
| petra | Petra Industrial Supplies | JO / JOD | B2B manufacturer/distributor (m, kg, ton) | ERP sales-lines Excel |
| bytefix | ByteFix Electronics | EG / EGP | Phones, accessories, repair services | English Excel |
| clarity | Clarity Conseil | FR / EUR | B2B consulting (hours, days, retainers) | French CSV |

Each has 18 months of history (April 2025 onwards) with seasonality
(Ramadan, Eid, summer, harvest, back-to-school, Black Friday), price changes,
launches and discontinuations, discounts, a growth trend and the country's own
weekend, plus competitors with observed prices, mixed-language customer
reviews and business documents (PDF) for the AI assistant.

```bash
cd backend
python -m scripts.demo_companies.generate --out-dir /tmp/demo --end 2026-10-05
python -m scripts.demo_companies.seed   --api https://<your-api> --data-dir /tmp/demo --password '<Strong!Pass1>' \
       [--email-pattern '{local}+{key}@yourdomain.com'] [--only zaytouna]
python -m scripts.demo_companies.verify --api https://<your-api> --data-dir /tmp/demo --password '<Strong!Pass1>'
```

`verify` recomputes dashboard revenue windows, the daily trend, review and
document processing and catalogue integrity from the generator's own ground
truth (`manifest.json`) and reports any difference.

`documents/` holds the generated PDFs (rebuild with
`python -m scripts.demo_companies.build_documents`, which needs reportlab).

## Local meeting fixture (Phase 1)

For the single isolated meeting tenant, use the checkout-scoped
`tools/dev/seed_meeting_demo.py` from the repository root. It reuses this
folder's bilingual Zaytouna catalog and the existing onboarding helper, but
uses the current structured invoice/inventory preview and confirmation API,
normal signup with Mailpit OTP, and dedicated Knowledge Base upload endpoint.
It creates no Stripe objects or entitlement overrides. Run `prepare`, then
`seed`; repeated `seed` calls replay the same reviewed confirmations. `verify`
reconciles the fixed business facts without requesting generation.

See [the Seed Truth Manifest and Phase 2 handoff](../../../docs/DEMO_SEED_PHASE1.md)
for commands, private credential location, actual counts, metrics and limits.
