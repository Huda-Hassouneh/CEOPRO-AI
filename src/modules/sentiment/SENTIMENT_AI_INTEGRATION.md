# Sentiment AI integration

The CEOPRO routes remain `POST /features/sentiment/analyze-pending` and `GET /features/sentiment/summary`. The analysis route reads eligible, unprocessed reviews from the tenant database and calls the models Space Gradio API `sentiment` in batches of at most 64 texts. It validates order and output shape, saves results locally, and meters the number processed.

The summary route aggregates CEOPRO's stored predictions and does not call the AI service. Country-filtered summaries are rejected because the review schema has no country field. The backend does not forward caller Authorization to Hugging Face.

See [`../../../INTEGRATIONS.md`](../../../INTEGRATIONS.md#sentiment) for configuration and details.
