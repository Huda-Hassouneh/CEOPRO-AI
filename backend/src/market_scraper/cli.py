"""Run one tenant-scoped collection using the source's reviewed collector."""

import argparse
import json
import os

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

from src.ai.core import operation_receipts
from src.market_scraper import data_access
from src.market_scraper.collectors import resolve_collector
from src.market_scraper.network_security import resolve_public_addresses


def run_collection(tenant_id: str, source_id: str, receipt_id: str | None = None) -> int:
    if not receipt_id:
        raise ValueError("a durable operation receipt is required")
    connection = data_access.get_tenant_connection(tenant_id)
    receipt = None
    try:
        worker_id = f"market-scraper-cli-{os.getpid()}"
        lease_seconds = int(os.getenv("SCRAPER_OPERATION_LEASE_SECONDS", "1800"))
        operation_receipts.recover_expired(connection, tenant_id)
        receipt = operation_receipts.claim(connection, tenant_id, receipt_id, worker_id, lease_seconds)
        if receipt["source_id"] != str(source_id):
            operation_receipts.finish(connection, receipt, "denied", "RECEIPT_SOURCE_MISMATCH")
            raise ValueError("receipt does not authorize this source")
        source = data_access.load_source(connection, tenant_id, source_id)
        if not source:
            operation_receipts.finish(connection, receipt, "denied", "SOURCE_NOT_FOUND")
            raise ValueError("active source not found")
        if source["policy_status"] != "ALLOWED":
            operation_receipts.finish(connection, receipt, "denied", "SOURCE_POLICY_CHANGED")
            raise ValueError("source policy must be ALLOWED before collection")
        if not all((
            source["approval_reference"], source["approved_at"],
            source["privacy_reviewed_at"],
        )):
            operation_receipts.finish(connection, receipt, "denied", "SOURCE_REVIEW_INCOMPLETE")
            raise ValueError("source requires recorded approval and privacy review")
        collector = resolve_collector(source)
        targets = data_access.load_scrape_targets(connection, tenant_id, source_id)
        resolve_public_addresses(source["source_url"])
        for target in targets:
            resolve_public_addresses(target["product_url"])
        job_id = receipt.get("ingestion_job_id")
        if not job_id:
            job_id = data_access.create_ingestion_job(connection, tenant_id, source_id, receipt=receipt)
            receipt["ingestion_job_id"] = job_id
        if collector.requires_targets and not targets:
            data_access.finish_ingestion_job(
                connection, tenant_id, job_id, "COMPLETED", 0, 0,
                "No active product mappings were allocated.",
                receipt=receipt,
                receipt_allow_pre_provider=True,
            )
            operation_receipts.finish(connection, receipt, "completed")
            return 0
        operation_receipts.begin_provider(connection, receipt)
    finally:
        connection.close()

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
        "operation_receipt_id": receipt["receipt_id"],
        "operation_worker_id": receipt["worker_id"],
        "operation_lease_generation": receipt["lease_generation"],
        "operation_actor_user_id": receipt["actor_user_id"],
        "operation_period_start": str(receipt["period_start"]),
        "operation_lease_seconds": receipt["lease_seconds"],
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
                connection, tenant_id, job_id, "FAILED", 0, len(targets), str(exc), receipt=receipt
            )
            operation_receipts.finish(connection, receipt, "reconciliation_required", "PROVIDER_OUTCOME_UNKNOWN")
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
                receipt=receipt,
            )
            status = "FAILED"
        operation_receipts.finish(
            connection, receipt, "completed" if status == "COMPLETED" else "reconciliation_required",
            None if status == "COMPLETED" else "PROVIDER_OUTCOME_UNKNOWN",
        )
    finally:
        connection.close()
    return 0 if status == "COMPLETED" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--receipt-id", required=True)
    args = parser.parse_args()
    raise SystemExit(run_collection(args.tenant_id, args.source_id, args.receipt_id))


if __name__ == "__main__":
    main()
