# Pricing AI integration

The public CEOPRO route remains `POST /features/pricing/recommend?product_id=<uuid>`. The backend reads the tenant-owned product, current/cost prices, competitor observations, and currency rates, then calls the analytics Space Gradio API `recommend` with positional input `[product, competitor_prices, exchange_rates]`.

The Gradio response is schema-validated. CEOPRO creates evidence and recommendation outcome records locally; model-supplied identifiers do not replace tenant-owned records. The existing CEOPRO response envelope and market statistics remain in place.

See [`../../../INTEGRATIONS.md`](../../../INTEGRATIONS.md#pricing-recommendation) for shared transport configuration and error behavior.
