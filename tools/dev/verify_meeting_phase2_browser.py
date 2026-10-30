"""Phase 2 real-browser check for the existing meeting seed, no response mocks.

Explicit generation actions are left to Phase 2. Existing page effects can
refresh local forecasts through the normal authorized pipeline.
Only the designated private demo login is used. No browser session is saved.
"""
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

import dev


def main():
    c = dev.config()
    if Path(sys.executable).resolve() != dev.PYTHON.resolve():
        import subprocess
        return subprocess.call([str(dev.PYTHON), str(Path(__file__).resolve())])
    from playwright.sync_api import sync_playwright
    from seed_meeting_demo import ACCOUNT, EMAIL, BUSINESS, read
    EVIDENCE = dev.STATE / "evidence" / "meeting-phase2"
    account = read(ACCOUNT)
    if account["email"] != EMAIL or account["business"] != BUSINESS or not account.get("tenant_id"):
        raise RuntimeError("Designated demo identity missing")
    chrome = dev.integrations(validate_providers=False).get("CHROMIUM_PATH")
    if not chrome:
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")):
            if base and (Path(base) / "Google/Chrome/Application/chrome.exe").exists():
                chrome = str(Path(base) / "Google/Chrome/Application/chrome.exe")
                break
    if not chrome:
        raise RuntimeError("Chrome unavailable; browser check BLOCKED")
    origin = f"http://127.0.0.1:{c['ports']['frontend']}"
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=chrome, headless=True)
        try:
            for locale, width in (("en", 1440), ("ar", 390)):
                context = browser.new_context(viewport={"width": width, "height": 1000})
                context.add_init_script("localStorage.setItem('ceopro_locale', " + json.dumps(locale) + ");")
                page = context.new_page()
                errors, denials = [], []
                page.on("pageerror", lambda error: errors.append(type(error).__name__))
                def response_check(response):
                    path = urlsplit(response.url).path
                    if response.status >= 400 and path.startswith("/api/"):
                        if response.status == 403 and path == "/api/platform/me":
                            denials.append("Tenant Owner correctly denied platform access")
                        else:
                            errors.append(f"HTTP {response.status} {path}")
                page.on("response", response_check)
                page.goto(origin + "/login")
                page.locator('input[type="email"]').fill(EMAIL)
                page.locator('input[type="password"]').fill(account["password"])
                page.locator('button[type="submit"]').click()
                page.wait_for_url(lambda u: not urlsplit(u).path.startswith("/login"), timeout=30000)
                tenant = page.evaluate("JSON.parse(localStorage.getItem('ceopro_auth_session')).tenantId")
                if tenant != account["tenant_id"]:
                    raise RuntimeError("Browser signed into unexpected tenant")
                for route in ("/dashboard", "/catalog", "/products", "/connect-data", "/demand", "/market", "/market/trends", "/pricing", "/reports", "/ai-advisor", "/marketing", "/billing"):
                    errors.clear()
                    page.goto(origin + route, wait_until="domcontentloaded")
                    page.wait_for_load_state("networkidle", timeout=25000)
                    page.wait_for_timeout(400)
                    text = page.locator("body").inner_text()
                    (EVIDENCE / ("body-"+locale+"-"+route.strip("/").replace("/", "-")+".txt")).write_text(text, encoding="utf-8")
                    findings = list(errors)
                    if urlsplit(page.url).path != route:
                        findings.append("Unexpected redirect")
                    if len(text.strip()) < 150:
                        findings.append("Page content missing")
                    if page.evaluate("document.documentElement.scrollWidth > innerWidth + 2"):
                        findings.append("Horizontal overflow")
                    if locale == "ar" and page.locator("html").get_attribute("dir") != "rtl":
                        findings.append("RTL missing")
                    # Concrete business evidence in the English UI; other
                    # routes are checked against API truth in the seeder.
                    if locale == "en" and route == "/dashboard" and "16,203" not in text:
                        findings.append("Expected 30-day revenue not visible")
                    if locale == "en" and route in ("/catalog", "/products") and "Extra Virgin Olive Oil 1L" not in text:
                        findings.append("Seed product not visible")
                    if locale == "en" and route == "/connect-data" and "synthetic-sales" not in text:
                        findings.append("Seed imports not visible")
                    label = route.strip("/").replace("/", "-")
                    page.screenshot(path=str(EVIDENCE / f"browser-{locale}-{label}.png"), full_page=True)
                    if locale == "en" and route == "/reports":
                        button = page.get_by_role("button", name="Export CSV", exact=True)
                        if button.count():
                            with page.expect_download(timeout=30000) as downloaded:
                                button.click()
                            downloaded.value.save_as(str(EVIDENCE / "browser-sales.csv"))
                        else:
                            findings.append("CSV export button not found")
                    result = {"locale": locale, "width": width, "route": route,
                              "status": "FAIL" if findings else "PASS", "findings": findings}
                    results.append(result)
                    print(f"{result['status']}: {locale} {route}" + ("; " + "; ".join(findings) if findings else ""), flush=True)
                context.close()
        finally:
            browser.close()
    result = {"status": "PASS" if all(x["status"] == "PASS" for x in results) else "FAIL",
              "response_mocks": False, "checks": results, "explicit_generation_actions_exercised": False,
              "automatic_local_forecasts": "Normal Products page effect; see final seed verification"}
    dev.write_json(EVIDENCE / "browser.json", result)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"BLOCKED: browser {type(exc).__name__}; credentials and session omitted", file=sys.stderr)
        sys.exit(1)
