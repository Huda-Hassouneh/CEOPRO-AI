# Market Perception Index integration

The CEOPRO route remains `GET /features/mpi/summary`. The backend selects up to 100 eligible tenant reviews and sends `[reviews, subject_type, subject_id, country_code, as_of]` to the models Space Gradio API `market_intelligence`.

CEOPRO persists evidence locally and maps the validated Gradio result to the existing `OK`/`UNKNOWN` response. Low-sample results remain unavailable rather than being converted to zero. The review schema has no country field, so the current request sends `null` for `country_code`.

See [`../../../INTEGRATIONS.md`](../../../INTEGRATIONS.md#mpi--market-perception) for shared transport details.
