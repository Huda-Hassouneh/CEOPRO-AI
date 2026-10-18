import { test } from "@playwright/test";

const blocked = (category: string, reason: string) => {
  test("BLOCKED — " + reason, async ({}, testInfo) => {
    testInfo.annotations.push({ type: "mode", description: "smart-alerts-e2e" });
    testInfo.annotations.push({ type: "failure-category", description: category });
    testInfo.annotations.push({ type: "recommended-investigation", description: reason });
    test.skip(true, `BLOCKED_NOT_IMPLEMENTED: ${reason}`);
  });
};

blocked("SMART_ALERT_DELIVERY_PATH_MISSING", "No producer connects market_alert_events to the tenant notification outbox, so alert-to-inbox delivery cannot be verified.");
blocked("SMART_ALERT_DELIVERY_PATH_MISSING", "No Smart Alerts worker event definition exists to verify transactional delivery, retries, or dead-letter state.");
blocked("SMART_ALERT_TENANT_ISOLATION_FAILURE", "No alert delivery API exists to verify recipient selection, tenant isolation, or RLS against two tenants.");
blocked("SMART_ALERT_ENTITLEMENT_BYPASS", "No system_alerts plan grant or rule/delivery entitlement boundary exists to exercise Starter, Growth, and Enterprise access.");
blocked("SMART_ALERT_RULES_UNAVAILABLE", "No tenant-scoped alert-rule create, list, update, or delete API exists.");
blocked("SMART_ALERT_LIFECYCLE_UNAVAILABLE", "No acknowledge/resolve API exists; notification read and archive receipts are separate states.");
blocked("SMART_ALERT_FALSE_SUCCESS_UI", "Notification preferences render as unavailable and no Smart Alerts settings screen is implemented.");
blocked("SMART_ALERT_FALSE_SUCCESS_UI", "No Smart Alerts page exists to verify localized loading, empty, error, and saved states or false-success behavior.");
blocked("SMART_ALERT_DUPLICATE_DELIVERY", "No alert-to-outbox path exists to exercise concurrent duplicate events or worker retries end to end.");
blocked("SMART_ALERT_PRICE_INTEGRITY", "No UI evidence contract exposes event currency and freshness, so a browser price-change explanation cannot be validated.");
