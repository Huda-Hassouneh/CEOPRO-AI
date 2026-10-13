# KEEL

KEEL turns a business's own sales, stock and pricing data, plus public
information about its market, into clear daily decisions: what to restock,
what to reprice, which competitors moved, what demand to expect and what to
promote. It works for any kind of business (shops, restaurants, cafés,
salons, pharmacies, B2B suppliers, services) in English and Arabic.

## What's in the product

| Area | What it does |
|---|---|
| Command Center | Today's numbers, the next best actions, products to restock, falling sales and market moves |
| Products & Sales | Every product with its sales, margin, stock cover and forecast; record sales; import history |
| Demand | 30-day demand forecast per product from the company's own sales history |
| Pricing | Prices and margins against real competitor prices, with a recommended price and its reasoning |
| Competitors | Discovery from public listings (OpenStreetMap, Google Maps), web search and businesses' own websites; tracked competitors, price changes, leaderboard and trends |
| Marketing | Guided campaign builder: copy and images for a chosen product, goal and audience |
| Assistant | Questions answered from the company's own data and documents, with sources |
| Reports | Financial summary and a sales report, exportable as CSV or JSON |
| Data & Documents | Spreadsheet uploads, live connections to a company's own database or API, documents |
| Alerts | Stock, sales, competitor price and market alerts, with read state |
| Settings & Billing | Profile, company, team and roles, notifications, language and theme, security, data export and deletion; plans, usage and Stripe checkout |

Every company is a separate workspace protected by Postgres row-level
security; one sign-in can own several companies.

## Run it

```bash
./keel setup     # once: .env files, Python and npm dependencies
./keel start     # databases, backend and frontend - open http://localhost:5173
./keel seed      # optional: seven demo companies with 18 months of history
./keel test      # all backend and frontend checks
```

Codespaces runs the same steps automatically. Full instructions, the
configuration names and troubleshooting are in **[RUNNING_LOCALLY.md](RUNNING_LOCALLY.md)**;
Codespaces specifics in [CODESPACES_DEVELOPMENT.md](CODESPACES_DEVELOPMENT.md);
staging on Render in [STAGING_DEPLOYMENT.md](STAGING_DEPLOYMENT.md).
What is finished and what still needs an account or a key is in
[CURRENT_STATUS.md](CURRENT_STATUS.md).

## Layout

- `backend/` - FastAPI service (`src/ai/main.py`), market data collection and
  competitor discovery (`src/market_scraper/`), forecasting, the assistant
  (RAG over the company's data and documents), billing, and the Postgres
  schema and migrations (`src/infrastructure/database/`).
- `frontend/` - React + Vite app. The design system lives in
  `src/styles/apex-theme.css` (tokens) and `src/styles/keel-glass.css` (the
  glass material); translations in `src/assets/locales/`.
- `.devcontainer/` - the Codespace definition and the setup scripts `./keel` uses.
- `render.yaml` - staging deployment.
- `docs/archive/` - historical reports kept for reference.
