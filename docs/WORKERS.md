# Services and workers — current review release

Run commands from the integrated `keel` root. Configure local secrets first; never commit them. Stop existing processes before starting replacements.

| Command | Purpose |
| --- | --- |
| `npm run dev` | Node API and React/Vite |
| `npm run api:store` | Stateless authenticated WooCommerce/Shopify adapter service, port 8002 |
| `npm run worker:store-sync` | Node scheduler, provider requests and canonical writes |
| `npm run api:insights` | Node-facing Python business insights, port 8001 |
| `npm run worker:ingestion` | Existing Node ingestion pipeline |
| `npm run worker:tenant-notifications` | Tenant notification delivery (withdrawn market alerts suppressed) |
| `npm run worker:platform-notifications` | Platform notification delivery |
| `npm run workers:market` | Disabled launcher; starts no process |
| `npm run worker:dispatch` | Disabled launcher; starts no process |
| Backend `npm run worker:market-tracking` | Disabled before runtime DB import |

The restored team Python workers remain in `ai/src/market_scraper/` without edits. They are not integrated with the Node schema/authorization contract in this release. Stop older running market workers; replacing files cannot cancel an already running old process. Do not flush Redis or delete queued data. See [COMPETITOR_REVIEW.md](COMPETITOR_REVIEW.md).

For local WooCommerce only, `cloudflared tunnel --url http://127.0.0.1:8088` publishes the test store. This is not a KEEL worker. Restarting a quick tunnel can change its URL; update WordPress and its KEEL connection accordingly.
