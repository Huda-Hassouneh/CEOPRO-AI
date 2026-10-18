"""Small Node-facing API; does not start scraper, LLM or digest workers.
Run: python -m uvicorn src.ai.insights.app:app --host 127.0.0.1 --port 8001 --env-file .env
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from src.ai import db
from src.ai.insights.api import router

@asynccontextmanager
async def lifecycle(_app):
    yield
    db.close_pool()

app=FastAPI(title='KEEL Business Insights',lifespan=lifecycle)
app.include_router(router)
@app.get('/health')
def health():return {'status':'ok','service':'keel-business-insights'}
