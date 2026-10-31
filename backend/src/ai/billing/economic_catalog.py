"""Runtime-backed coverage, not a price list or an operational health check.

Version with changes to the cited enforcement paths. Owner policies retain
precedence; conflicts with Credit-funded calls are reported, never added twice.
No provider modules are imported and no credentials leave this module.
"""
import os
from datetime import date

VERSION = 'runtime-economics-2026-10-v1'

# code: (coverage, customer capability, enforcement evidence)
FEATURES = {
    'ai_credits': ('ai_credits', 'AI provider spending allowance', 'billing/credits.py:provider_call'),
    'data_credits': ('data_credits', 'Data provider spending allowance', 'market_scraper/provider_billing.py:metered_request'),
    'rag_assistant': ('ai_and_data_credits', 'Assistant tokens; optional metered research', 'routers/rag.py:credits.metering; rag/llm_client.py; research/research.py'),
    'marketing_image_generation': ('ai_credits', 'Generated marketing images and copy', 'marketing/image_generation.py; routers/marketing.py'),
    'web_searches': ('data_credits', 'External web searches', 'market_scraper/web_search.py; market_scraper/provider_billing.py'),
    'tracked_competitors': ('data_credits', 'Competitor capacity and discovery', 'market_scraper/tenant_discovery.py; market_scraper/competitor_enrichment.py'),
    'competitor_management': ('ai_and_data_credits', 'Competitor monitoring; optional AI analysis', 'market_scraper/competitor_enrichment.py; market_inputs/competitor_analysis.py'),
    'market_intelligence': ('ai_and_data_credits', 'Market evidence; optional research/analysis', 'market_inputs/competitor_intel.py; mpi/pipeline.py; research/research.py'),
    'sentiment_analysis': ('internal_allocation', 'Local sentiment model per review', 'sentiment/model.py; sentiment/pipeline.py'),
    'demand_prediction': ('internal_allocation', 'Local forecasting', 'forecasting/authorization.py; forecasting/pipeline.py'),
    'document_extraction': ('internal_allocation', 'Local parsing/OCR per uploaded KB', 'extraction/durable_uploads.py; extraction/structured_business.py'),
    'document_storage_mb': ('internal_allocation', 'Stored document capacity', 'core/usage.py; extraction/durable_uploads.py'),
    'connected_data_sources': ('internal_allocation', 'Connection capacity; remote account terms remain separate', 'core/usage.py; market_scraper/connector_sync.py'),
    'tracked_products': ('internal_allocation', 'Product capacity; discovery charged separately to Data Credits', 'core/usage.py; extraction/promotion.py'),
    'monthly_reports': ('internal_allocation', 'Local report/export jobs', 'routers/reports.py'),
    'team_seats': ('internal_allocation', 'User seat capacity', 'core/usage.py'),
    'dashboard_analytics': ('internal_allocation', 'Local dashboard analysis', 'routers/dashboard.py'),
    'product_management': ('internal_allocation', 'Product management', 'core/usage.py:TRACKED_PRODUCTS'),
    'data_integration': ('internal_allocation', 'Import and connection management', 'market_scraper/connector_sync.py'),
}

# Provider keys exactly match billing/credits.py and provider_billing.py.
# Every entry is an alternative/optional path, not a dependency of every plan.
# Credentials here mean presence only; validity, quota and network are untested.
PROVIDERS = {
    'groq': ('ai', 'openai/gpt-oss-20b', ['input_token', 'output_token'], ['GROQ_API_KEY']),
    'local_llm': ('ai', '*', ['input_token', 'output_token'], ['LOCAL_LLM_BASE_URL']),
    'huggingface_llm': ('ai', None, ['input_token', 'output_token'], ['HUGGINGFACE_API_TOKEN', 'HUGGINGFACE_LLM_MODEL']),
    'paid': ('ai', None, ['input_token', 'output_token'], ['PAID_LLM_BASE_URL', 'PAID_LLM_API_KEY']),
    'tavily': ('data', 'search', ['request'], ['TAVILY_API_KEY']),
    'brave_search': ('data', 'search', ['request'], ['BRAVE_SEARCH_API_KEY']),
    'google_cse': ('data', 'search', ['request'], ['GOOGLE_CUSTOM_SEARCH_API_KEY', 'GOOGLE_CUSTOM_SEARCH_CX']),
    'google_places': ('data', 'text_search', ['request'], ['GOOGLE_PLACES_API_KEY']),
    'google_geocoding': ('data', 'geocode', ['request'], ['GOOGLE_PLACES_API_KEY']),
    'apify': ('data', 'actor_run', ['record'], ['APIFY_API_TOKEN']),
    'serpapi': ('data', 'search', ['request'], ['SERPAPI_API_KEY']),
    'gemini_vision': ('data', 'read_image', ['request'], ['GEMINI_API_KEYS']),
    'searxng': ('data', 'search', ['request'], ['SEARXNG_INSTANCE_URL']),
    **{p: ('ai', 'image_generation', ['image'], keys) for p, keys in {
        'local_image': ['LOCAL_IMAGE_BASE_URL'], 'huggingface': ['HUGGINGFACE_API_TOKEN'],
        'cloudflare': ['CLOUDFLARE_ACCOUNT_ID', 'CLOUDFLARE_API_TOKEN'],
        'together': ['TOGETHER_API_KEYS'], 'gemini': ['GEMINI_API_KEYS'],
        'pollinations': ['POLLINATIONS_API_KEYS'], 'aihorde': [],
    }.items()},
}


def coverage():
    return {code: dict(feature_code=code, treatment=row[0], capability=row[1], source=row[2],
                       provider_paths=(['llm', 'data_collectors'] if row[0] == 'ai_and_data_credits' else
                          ['images', 'llm'] if code == 'marketing_image_generation' else
                          ['llm', 'images'] if code == 'ai_credits' else
                          ['data_collectors'] if row[0] == 'data_credits' else []),
                       catalog_version=VERSION) for code, row in FEATURES.items()}


def provenance(row):
    author = row.get('configured_by') or ''
    if author.startswith(('migration ', 'ai-provider-pricing-', 'billing-catalog-')):
        return 'catalog/bootstrap'
    return 'owner/operator' if author else 'unknown'


def readiness(schedules, settings=None, as_of=None, max_rate_age_days=None):
    settings = os.environ if settings is None else settings
    settings = dict(settings)
    for primary, alias in [('APIFY_API_TOKEN', 'APIFY_TOKEN'), ('GOOGLE_PLACES_API_KEY', 'GOOGLE_MAPS_API_KEY')]:
        settings[primary] = settings.get(primary) or settings.get(alias)
    if settings.get('CLOUDFLARE_ACCOUNTS'):
        settings['CLOUDFLARE_ACCOUNT_ID'] = settings['CLOUDFLARE_API_TOKEN'] = True
    settings['LOCAL_IMAGE_BASE_URL'] = settings.get('LOCAL_IMAGE_BASE_URLS') or settings.get('LOCAL_IMAGE_BASE_URL')
    today = as_of or date.today().isoformat()
    rows = []
    for key, (budget, operation, units, required) in PROVIDERS.items():
        provider = {'local_llm': 'local', 'local_image': 'local', 'huggingface_llm': 'huggingface'}.get(key, key)
        if key == 'groq':
            operation = settings.get('GROQ_MODEL') or operation
        if key == 'huggingface_llm':
            operation = settings.get('HUGGINGFACE_LLM_MODEL')
        if key == 'paid':
            operation = settings.get('PAID_LLM_MODEL') or settings.get('GROQ_MODEL') or 'openai/gpt-oss-20b'
        evidence = []
        for unit in units:
            candidates = [r for r in schedules if r['provider'] == provider and r['budget_kind'] == budget
                          and operation is not None and r['operation'] in (operation, '*') and r['unit'] == unit]
            rate = next((r for r in candidates if r['operation'] == operation), candidates[0] if candidates else None)
            status = 'MISSING'
            if rate and rate.get('unit_cost_usd') is not None:
                status = 'VERIFIED' if (rate.get('verified_at') and str(rate['verified_at']) <= today
                    and rate.get('source') and rate.get('cost_is_final')) else 'UNVERIFIED'
                if status == 'VERIFIED' and max_rate_age_days is not None and (
                    date.fromisoformat(today) - date.fromisoformat(str(rate['verified_at']))).days > max_rate_age_days:
                    status = 'STALE'
            evidence.append(dict(unit=unit, status=status, schedule_id=rate.get('schedule_id') if rate else None,
                                 provenance=provenance(rate) if rate else None))
        missing = [name for name in required if not settings.get(name)
                   and not (key == 'huggingface' and name == 'HUGGINGFACE_API_TOKEN' and settings.get('HUGGINGFACE_API_TOKENS'))]
        rows.append(dict(provider=key, budget=budget, operation=operation, rates=evidence,
            credential_status='MISSING' if missing else 'PRESENT_UNTESTED' if required else 'NOT_REQUIRED',
            missing_settings=missing, operational_status='UNVERIFIED',
            approval_requirements=(['PLACES_TERMS_APPROVAL_REFERENCE (review storage only)'] if key == 'google_places' else [])))
    return dict(catalog_version=VERSION, providers=rows,
        unmetered_public_providers=['openstreetmap', 'nominatim', 'photon', 'wikidata', 'overture', 'gdelt', 'openfoodfacts', 'youtube'],
        approvals=[dict(setting=k, present=bool(settings.get(k))) for k in (
            'PLACES_TERMS_APPROVAL_REFERENCE', 'EXTERNAL_COMMENTS_APPROVAL_REFERENCE', 'SOCIAL_CONTENT_APPROVAL_REFERENCE')],
        note='Optional paths. Presence does not prove credentials valid, approval sufficient, free-tier eligibility or service availability. Source terms/robots and tenant source approvals remain independently enforced.')
