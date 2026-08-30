"""Safe defaults for the CEOPRO market scraper."""

import os

BOT_NAME = "ceopro_market_scraper"
SPIDER_MODULES = ["src.market_scraper.spiders"]
NEWSPIDER_MODULE = "src.market_scraper.spiders"

ROBOTSTXT_OBEY = True
USER_AGENT = os.getenv(
    "SCRAPER_USER_AGENT",
    "CEOPRO-MarketResearchBot/1.0 (+https://github.com/Huda-Hassouneh/CEOPRO-AI)",
)
CONCURRENT_REQUESTS = 8
CONCURRENT_REQUESTS_PER_DOMAIN = 4
DOWNLOAD_DELAY = 0.25
DOWNLOAD_TIMEOUT = 30
RETRY_TIMES = 2
COOKIES_ENABLED = False
TELNETCONSOLE_ENABLED = False

DOWNLOADER_MIDDLEWARES = {
    "src.market_scraper.middlewares.PublicNetworkBoundaryMiddleware": 50,
}

AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 0.5
AUTOTHROTTLE_MAX_DELAY = 10.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 2.0

ITEM_PIPELINES = {
    "src.market_scraper.staging.PostgresMarketStagingPipeline": 50,
    "src.market_scraper.pipelines.ValidateMarketRecordPipeline": 100,
    "src.market_scraper.pipelines.DeduplicateMarketRecordPipeline": 200,
    "src.market_scraper.persistence.PostgresPricePipeline": 300,
}

FEED_EXPORT_ENCODING = "utf-8"
FEED_EXPORT_INDENT = None
LOG_LEVEL = "INFO"
