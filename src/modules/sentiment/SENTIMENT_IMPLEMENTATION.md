# Archived sentiment implementation notes

This document described the previous FastAPI batch and mock flow. The active integration loads pending reviews from CEOPRO and calls the Gradio `sentiment` model in bounded batches.

See [SENTIMENT_AI_INTEGRATION.md](SENTIMENT_AI_INTEGRATION.md) and [INTEGRATIONS.md](../../../INTEGRATIONS.md#sentiment) for the current contract.
