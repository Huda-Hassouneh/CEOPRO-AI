"""Stable executable feature identifiers; no catalog values or infrastructure imports."""
RAG_ASSISTANT = "rag_assistant"
WEB_SEARCHES = "web_searches"
IMAGE_GENERATION = "marketing_image_generation"
TRACKED_PRODUCTS = "tracked_products"
TRACKED_COMPETITORS = "tracked_competitors"
DOCUMENT_STORAGE_MB = "document_storage_mb"
DOCUMENT_EXTRACTION = "document_extraction"   # KB processed per billing period
SENTIMENT_ANALYSIS = "sentiment_analysis"     # records analysed per billing period
CONNECTED_DATA_SOURCES = "connected_data_sources"
MONTHLY_REPORTS = "monthly_reports"           # report exports per billing period
TEAM_SEATS = "team_seats"                     # active members of the company
DATA_CREDITS = "data_credits"                 # billing/credits.py meters these two
AI_CREDITS = "ai_credits"
CREDIT_FEATURES = (DATA_CREDITS, AI_CREDITS)

# Included modules (usage_plan_entitlements), as in the plan catalog.
MARKET_INTELLIGENCE = "market_intelligence"
DEMAND_PREDICTION = "demand_prediction"
COMPETITOR_MANAGEMENT = "competitor_management"

# Stable executable identities shared by catalog validation and authoring.
# Presentation categories and bootstrap values do not participate in enforcement.
QUANTITATIVE_FEATURES = (
    TRACKED_PRODUCTS, MONTHLY_REPORTS, TEAM_SEATS, DATA_CREDITS, AI_CREDITS,
    DOCUMENT_STORAGE_MB, CONNECTED_DATA_SOURCES, IMAGE_GENERATION, SENTIMENT_ANALYSIS,
    DOCUMENT_EXTRACTION, RAG_ASSISTANT, WEB_SEARCHES, TRACKED_COMPETITORS,
)
MODULE_FEATURES = (MARKET_INTELLIGENCE, DEMAND_PREDICTION, COMPETITOR_MANAGEMENT)
BASELINE_ENTITLEMENTS = ("dashboard_analytics", "product_management", "data_integration")
