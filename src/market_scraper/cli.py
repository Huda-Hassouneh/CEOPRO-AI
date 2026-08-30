"""Run one tenant-scoped collection using the source's reviewed collector."""

import argparse
import json
import os

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

from src.market_scraper import data_access
from src.market_scraper.collectors import resolve_collector
from src.market_scraper.network_security import resolve_public_addresses


def run_collection(tenant_id: str, source_id: str) -> int:
    connection = data_access.get_tenant_connection(tenant_id)
    try:
        stale_minutes = int(os.getenv("SCRAPER_STALE_JOB_MINUTES", "30"))
        data_access.recover_stale_ingestion_jobs(connection, tenant_id, stale_minutes)
        source = data_access.load_source(connection, tenant_id, source_id)
        if not source:
            raise ValueError("active source not found")
        if source["policy_status"] != "ALLOWED":
            raise ValueError("source policy must be ALLOWED before collection")
        if not all((
            source["approval_reference"], source["approved_at"],
            source["privacy_reviewed_at"],
        )):
            raise ValueError("source requires recorded approval and privacy review")
        collector = resolve_collector(source)
        targets = data_access.load_scrape_targets(connection, tenant_id, source_id)
        resolve_public_addresses(source["source_url"])
        for target in targets:
            resolve_public_addresses(target["product_url"])
        job_id = data_access.create_ingestion_job(connection, tenant_id, source_id)
    finally:
        connection.close()

    if collector.requires_targets and not targets:
        connection = data_access.get_tenant_connection(tenant_id)
        try:
            data_access.finish_ingestion_job(
                connection, tenant_id, job_id, "COMPLETED", 0, 0,
                "No active product mappings were allocated.",
            )
        finally:
            connection.close()
        return 0

    settings = get_project_settings()
    requests_per_minute = max(1, int(source["rate_limit_per_minute"]))
    settings.set("DOWNLOAD_DELAY", 60.0 / requests_per_minute, priority="cmdline")
    if source["render_javascript"]:
        settings.set("DOWNLOAD_HANDLERS", {
            "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
            "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        }, priority="cmdline")
        settings.set("TWISTED_REACTOR", "twisted.internet.asyncioreactor.AsyncioSelectorReactor", priority="cmdline")

    common = {
        "targets_json": json.dumps(targets), "source_name": source["source_name"],
        "collection_method": source["collection_method"], "tenant_id": tenant_id,
        "source_id": source_id, "job_id": job_id,
    }
    if collector.spider.name == "books_to_scrape":
        common.update(start_url=source["source_url"], source_status=source["policy_status"])
    else:
        common.update(
            source_url=source["source_url"],
            render_javascript=str(source["render_javascript"]).lower(),
            collector_config_json=json.dumps(source["collector_config"]),
            credentials_json=json.dumps(source.get("connection_credentials", {})),
        )
    try:
        process = CrawlerProcess(settings)
        process.crawl(collector.spider, **common)
        process.start()
    except Exception as exc:
        connection = data_access.get_tenant_connection(tenant_id)
        try:
            data_access.finish_ingestion_job(
                connection, tenant_id, job_id, "FAILED", 0, len(targets), str(exc)
            )
        finally:
            connection.close()
        return 1

    connection = data_access.get_tenant_connection(tenant_id)
    try:
        status = data_access.load_ingestion_job_status(connection, tenant_id, job_id)
        if status == "PROCESSING":
            data_access.finish_ingestion_job(
                connection, tenant_id, job_id, "FAILED", 0, len(targets),
                "Crawler exited without finalizing the ingestion job",
            )
            status = "FAILED"
    finally:
        connection.close()
    return 0 if status == "COMPLETED" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--source-id", required=True)
    args = parser.parse_args()
    raise SystemExit(run_collection(args.tenant_id, args.source_id))


if __name__ == "__main__":
    main()
