# Python services — integrated review release

The current team Python source is installed here from its `backend/` directory. The full `src/market_scraper/` subtree and pricing competitor-classification file are restored without changes; hash verification is available from the root.

The integrated Node application starts only the appropriate adapters:

| Command from root | Service |
| --- | --- |
| `npm run api:store` | Stateless Node-authenticated WooCommerce/Shopify pages, port 8002 |
| `npm run api:insights` | Node-authenticated business findings, port 8001 |

Store adapters do not write canonical database records or own subscriptions. Node applies authorization, limits, scheduling and canonical writes. Insights reuses recorded data and checks Node tenant/session context.

The team's full FastAPI app, worker supervisor, migrations and deployment files remain available as source. They have standalone schema/auth/billing assumptions and are not substitutes for the Node integration. The custom competitor bridge is suspended; do not start the restored standalone market workers against KEEL_DEV.

Retained overlays and review scope: [COMPETITOR_REVIEW.md](../docs/COMPETITOR_REVIEW.md). Configuration: [.env.example](.env.example), [environment guide](../docs/ENVIRONMENT.md). Existing team notes deeper in this tree retain their original context and may reference paths from the standalone repository.
