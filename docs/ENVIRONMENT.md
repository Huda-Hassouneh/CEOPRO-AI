# Environment reference — review release

Keep local `.env` files private. The examples contain placeholders/commented optional values. Root launchers load the environment belonging to each child service. Preserve existing credential-encryption keys and database passwords; replacing source does not rotate them.

| Profile | Configuration |
| --- | --- |
| Node API | `backend/.env`: restricted `DATABASE_URL`, JWT secrets, origins and the existing integrations used by your tenant |
| Prisma deployment | `BOOTSTRAP_DATABASE_URL` administrative migration role on the existing development database; never substitute it for runtime `DATABASE_URL` |
| React | `frontend/.env`: public API URL only; no secrets in `VITE_` variables |
| Store adapter | `ai/.env`: `STORE_CONNECTOR_SERVICE_SECRET`, shared with Node |
| Store sync | Existing Node database and dispatcher-role connections, `STORE_CONNECTOR_API_URL`, stable `STORE_CONNECTOR_ENCRYPTION_KEY` and service secret |
| Business insights | Python `DATABASE_URL` host/database, `APP_DB_PASSWORD` for the restricted role, and shared Node `JWT_SECRET` |
| Docker | Root `.env`: the existing Compose project/database/administrator settings; do not select another project/volume to resolve an authentication error |
| Competitor workers | Suspended. `MARKET_TRACKING_ENABLED=true` cannot override source guards. Restored standalone team environment options are references, not instructions to start them against KEEL_DEV. |

WooCommerce quick-tunnel URL and Shopify OAuth callback changes still need the corresponding provider/connection configuration. They are not resolved by changing database credentials.

`ENVIRONMENT_VARIABLES.csv` and `ENVIRONMENT_SOURCE_MAP.json` are regenerated static inventories for this review. They include dormant and standalone AI consumers; they are not a list of mandatory values. Dynamic environment lookups may not appear. Optional settings stay commented so defaults and numeric parsing are preserved. Read the consuming module before overriding an unfamiliar standalone knob. Node remains the owner of subscriptions and permissions for the integrated application.
