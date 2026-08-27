"""Safe defaults for the CEOPRO market scraper."""

BOT_NAME = "ceopro_market_scraper"
SPIDER_MODULES = ["src.market_scraper.spiders"]
NEWSPIDER_MODULE = "src.market_scraper.spiders"

ROBOTSTXT_OBEY = True
USER_AGENT = "CEOPRO-MarketResearchBot/0.1 (+public-data; contact=team@ceopro.local)"
CONCURRENT_REQUESTS = 8
CONCURRENT_REQUESTS_PER_DOMAIN = 4
DOWNLOAD_DELAY = 0.25
DOWNLOAD_TIMEOUT = 30
RETRY_TIMES = 2
COOKIES_ENABLED = False
TELNETCONSOLE_ENABLED = False

AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 0.5
AUTOTHROTTLE_MAX_DELAY = 10.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 2.0

ITEM_PIPELINES = {
    "src.market_scraper.pipelines.ValidateMarketRecordPipeline": 100,
    "src.market_scraper.pipelines.DeduplicateMarketRecordPipeline": 200,
}

FEED_EXPORT_ENCODING = "utf-8"
FEED_EXPORT_INDENT = None
LOG_LEVEL = "INFO"
