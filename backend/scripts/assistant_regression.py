"""
KEEL - business assistant regression suite, against a running API and its database.

Every case asks the real /rag/query endpoint (sessions, roles, follow-ups and all)
and checks the reply against ground truth computed HERE with independent SQL on
the same database - not against the assistant's own code, and not merely "the
reply is not empty". A case passes only when the figure the question asks for is
in the answer, and (where it applies) a figure it must NOT contain is absent: the
wrong period's revenue, another company's data, or figures the member's role may
not see.

    cd backend && python -m scripts.assistant_regression --api http://127.0.0.1:8000 \\
        --password '...' [--report out.json]

Needs the demo companies (python -m scripts.demo_companies.seed --only zaytouna bytefix)
and DATABASE_URL (an admin connection, for the ground truth). Optional: --staff-email,
a staff member of Zaytouna (the permission cases are skipped without one).

When the language model is unavailable the assistant answers in evidence mode
(the records it found, unsummarised); the same checks apply to that answer. The
report gives the answer mode of every reply so a run with and without a model can
be told apart.
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import date, timedelta
from decimal import Decimal

import httpx
import psycopg2

ZAYTOUNA = "rania@zaytouna.keel-demo.example"
BYTEFIX = "mostafa@bytefix.keel-demo.example"
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


# --- ground truth -----------------------------------------------------------------

class Truth:
    def __init__(self, url: str):
        self.conn = psycopg2.connect(url)
        self.conn.autocommit = True

    def one(self, sql, *args):
        with self.conn.cursor() as cursor:
            cursor.execute(sql, args)
            return cursor.fetchone()

    def all(self, sql, *args):
        with self.conn.cursor() as cursor:
            cursor.execute(sql, args)
            return cursor.fetchall()

    def tenant(self, email):
        return str(self.one("SELECT tu.tenant_id FROM tenant_users tu JOIN users u ON u.user_id = tu.user_id "
                            "WHERE u.email = %s ORDER BY tu.joined_at LIMIT 1;", email)[0])

    def today(self, tenant):
        return self.one("SELECT (now() AT TIME ZONE COALESCE(timezone, 'UTC'))::date FROM companies "
                        "WHERE tenant_id = %s;", tenant)[0]

    def revenue(self, tenant, start, end):
        """invoices.total_amount in [start, end), in the company's time zone."""
        return self.one("SELECT COALESCE(SUM(total_amount), 0), COUNT(*) FROM invoices i JOIN companies c "
                        "ON c.tenant_id = i.tenant_id WHERE i.tenant_id = %s AND (i.issue_date AT TIME ZONE "
                        "COALESCE(c.timezone, 'UTC'))::date >= %s AND (i.issue_date AT TIME ZONE "
                        "COALESCE(c.timezone, 'UTC'))::date < %s;", tenant, start, end)

    def product_sales(self, tenant, name, start, end):
        return self.one("SELECT COALESCE(SUM(ii.quantity), 0), COALESCE(SUM(ii.total_price), 0) FROM invoice_items ii "
                        "JOIN invoices i ON i.invoice_id = ii.invoice_id AND i.tenant_id = ii.tenant_id "
                        "JOIN products p ON p.product_id = ii.product_id AND p.tenant_id = ii.tenant_id "
                        "JOIN companies c ON c.tenant_id = i.tenant_id "
                        "WHERE ii.tenant_id = %s AND p.product_name->>'en' = %s AND (i.issue_date AT TIME ZONE "
                        "COALESCE(c.timezone, 'UTC'))::date >= %s AND (i.issue_date AT TIME ZONE "
                        "COALESCE(c.timezone, 'UTC'))::date < %s;", tenant, name, start, end)

    def top_product(self, tenant, start, end, by="revenue"):
        order = "SUM(ii.total_price)" if by == "revenue" else "SUM(ii.quantity)"
        return self.one(f"SELECT p.product_name->>'en', SUM(ii.quantity), SUM(ii.total_price) FROM invoice_items ii "
                        f"JOIN invoices i ON i.invoice_id = ii.invoice_id AND i.tenant_id = ii.tenant_id "
                        f"JOIN products p ON p.product_id = ii.product_id AND p.tenant_id = ii.tenant_id "
                        f"JOIN companies c ON c.tenant_id = i.tenant_id "
                        f"WHERE ii.tenant_id = %s AND (i.issue_date AT TIME ZONE COALESCE(c.timezone, 'UTC'))::date >= %s "
                        f"AND (i.issue_date AT TIME ZONE COALESCE(c.timezone, 'UTC'))::date < %s "
                        f"GROUP BY 1 ORDER BY {order} DESC LIMIT 1;", tenant, start, end)

    def stock(self, tenant, name):
        return self.one("SELECT inv.stock_quantity FROM inventory inv JOIN products p ON p.product_id = inv.product_id "
                        "AND p.tenant_id = inv.tenant_id WHERE inv.tenant_id = %s AND p.product_name->>'en' = %s;",
                        tenant, name)[0]

    def forecast(self, tenant, name):
        return self.one("SELECT df.expected_demand FROM demand_forecasts df JOIN products p ON p.product_id = df.product_id "
                        "AND p.tenant_id = df.tenant_id WHERE df.tenant_id = %s AND p.product_name->>'en' = %s "
                        "ORDER BY df.created_at DESC LIMIT 1;", tenant, name)[0]

    def price(self, tenant, name):
        return self.one("SELECT current_price FROM products WHERE tenant_id = %s AND product_name->>'en' = %s;",
                        tenant, name)[0]

    def reviews(self, tenant, start=None, end=None):
        return self.one("SELECT COUNT(*), AVG(review_rating) FROM reviews WHERE tenant_id = %s AND safety_status = 'SAFE' "
                        "AND subject_type IN ('BUSINESS', 'PRODUCT') AND (%s::date IS NULL OR review_date >= %s::date) "
                        "AND (%s::date IS NULL OR review_date < %s::date);", tenant, start, start, end, end)

    def names(self, tenant, english):
        """(English name, Arabic name) of a product - either may name it in an answer."""
        row = self.one("SELECT product_name->>'en', product_name->>'ar' FROM products WHERE tenant_id = %s "
                       "AND product_name->>'en' = %s;", tenant, english)
        return tuple(n for n in row if n) if row else (english,)

    def product_names(self, tenant):
        return [r[0] for r in self.all("SELECT product_name->>'en' FROM products WHERE tenant_id = %s;", tenant)]


def month_bounds(today: date, back: int = 1):
    first = today.replace(day=1)
    for _ in range(back):
        first = (first - timedelta(days=1)).replace(day=1)
    following = (first + timedelta(days=32)).replace(day=1)
    return first, following


# --- checking a reply ---------------------------------------------------------------

def numbers(text: str):
    text = (text or "").translate(_DIGITS)
    return [Decimal(m.replace(",", "")) for m in re.findall(r"\d[\d,]*(?:\.\d+)?", text)]


def has_number(text: str, value) -> bool:
    """`value` is in `text`, exactly or as the model may round it (0-3 decimals)."""
    value = Decimal(str(value))
    found = numbers(text)
    for places in (3, 2, 1, 0):
        target = round(value, places)
        if any(n == target for n in found):
            return True
    return any(abs(n - value) <= Decimal("0.001") for n in found)


class Case:
    def __init__(self, key, category, questions, *, expect=(), expect_text=(), forbid=(), forbid_text=(),
                 who="owner", tenant_email=ZAYTOUNA, source="", correct="", status=None):
        self.key, self.category, self.questions = key, category, questions
        self.expect, self.expect_text, self.forbid, self.forbid_text = expect, expect_text, forbid, forbid_text
        self.who, self.tenant_email, self.source, self.correct, self.status = who, tenant_email, source, correct, status


def build_cases(truth: Truth, staff_email):
    z, b = truth.tenant(ZAYTOUNA), truth.tenant(BYTEFIX)
    today = truth.today(z)
    last_start, last_end = month_bounds(today, 1)
    prev_start, prev_end = month_bounds(today, 2)
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)
    tomorrow = today + timedelta(days=1)
    rolling30 = truth.revenue(z, today - timedelta(days=29), tomorrow)[0]
    last_month = truth.revenue(z, last_start, last_end)
    march = truth.revenue(z, date(today.year, 3, 1), date(today.year, 4, 1))
    q2_now = truth.revenue(z, date(today.year, 4, 1), date(today.year, 7, 1))
    q2_before = truth.revenue(z, date(today.year - 1, 4, 1), date(today.year - 1, 7, 1))
    mtd = truth.revenue(z, month_start, tomorrow)
    top_units_ytd = truth.top_product(z, year_start, tomorrow, by="units")
    top_prev_month = truth.top_product(z, prev_start, prev_end, by="revenue")
    sidr_last = truth.product_sales(z, "Sidr Honey 500g", last_start, last_end)
    evoo_last = truth.product_sales(z, "Extra Virgin Olive Oil 1L", last_start, last_end)
    reviews_all = truth.reviews(z)
    last90 = truth.reviews(z, today - timedelta(days=89), tomorrow)
    bytefix_last = truth.revenue(b, last_start, last_end)
    zaytouna_names = [n for n in truth.product_names(z) if n]
    month_name = last_start.strftime("%B")
    cases = [
        Case("sales-last-month-en", "sales", ["What was my total revenue last month?"],
             expect=[last_month[0]], forbid=[rolling30],
             source="invoices (calendar month)", correct=f"{month_name} revenue {last_month[0]} JOD, not the 30-day {rolling30}"),
        Case("sales-named-month-en", "sales", [f"How much did we sell in March {today.year}?"], expect=[march[0]],
             source="invoices (March)", correct=f"March revenue {march[0]}"),
        Case("sales-named-month-ar", "sales/arabic", ["كم كانت مبيعاتي في شهر آذار؟"], expect=[march[0]],
             source="invoices (March)", correct=f"March revenue {march[0]}"),
        Case("sales-quarter-comparison", "sales/comparison",
             [f"Compare my sales in Q2 {today.year} with Q2 {today.year - 1}"], expect=[q2_now[0], q2_before[0]],
             source="invoices (two quarters)", correct=f"Q2 {today.year} {q2_now[0]} vs Q2 {today.year - 1} {q2_before[0]}"),
        Case("sales-mtd-mixed-language", "sales/mixed", ["what's my revenue هالشهر؟"],
             **({"expect": [mtd[0]]} if mtd[0] else {"expect_text": ["no sales"]}),
             source="invoices (month to date)", correct=f"month-to-date revenue {mtd[0]}"),
        Case("top-product-units-ytd", "products", ["What was my top selling product this year by units?"],
             expect=[top_units_ytd[1]], expect_text=[top_units_ytd[0]],
             source="invoice_items (year to date, by units)", correct=f"{top_units_ytd[0]}, {top_units_ytd[1]} units"),
        Case("named-product-month", "products", [f"How many units of Sidr Honey 500g did we sell in {month_name}?"],
             expect=[sidr_last[0]], source="invoice_items (product, month)", correct=f"{sidr_last[0]} units"),
        Case("follow-up-periods", "follow-up",
             [f"What were my sales in {month_name} {last_start.year}?", "and the month before?",
              "which product sold the most then?"],
             expect=[top_prev_month[2]], expect_text=[top_prev_month[0]],
             source="invoices + invoice_items, period carried across turns",
             correct=f"previous month's top product {top_prev_month[0]} ({top_prev_month[2]} JOD)"),
        Case("follow-up-product", "follow-up",
             ["What's the price of Sidr Honey 500g?", "how many did we sell last month?", "and its stock?"],
             expect=[truth.stock(z, "Sidr Honey 500g")], source="inventory, product carried across turns",
             correct=f"stock {truth.stock(z, 'Sidr Honey 500g')}"),
        Case("follow-up-product-sales", "follow-up",
             ["What's the price of Sidr Honey 500g?", "how many did we sell last month?"],
             expect=[sidr_last[0]], source="invoice_items, product carried", correct=f"{sidr_last[0]} units"),
        Case("stock-arabic-partial-name", "inventory/arabic", ["كم المخزون عندي من زيت الزيتون؟"],
             expect=[truth.stock(z, "Extra Virgin Olive Oil 1L"), truth.stock(z, "Olive Oil Tin 4L")],
             source="inventory (all olive oil products)", correct="each olive oil product's stock"),
        Case("forecast-partial-name", "forecast", ["What is the demand forecast for olive oil next month?"],
             expect=[truth.forecast(z, "Extra Virgin Olive Oil 1L")], source="demand_forecasts",
             correct=f"Extra Virgin Olive Oil 1L: {truth.forecast(z, 'Extra Virgin Olive Oil 1L')} units"),
        Case("reviews-arabic", "sentiment/arabic", ["شو رأي الزبائن فينا؟"], expect=[reviews_all[0]],
             source="reviews + sentiment_results", correct=f"{reviews_all[0]} reviews"),
        Case("sentiment-change", "sentiment", ["Has customer sentiment improved over the last 3 months?"],
             expect=[last90[0]], forbid_text=["customs"], source="reviews by period",
             correct=f"{last90[0]} reviews in the last 90 days, compared with the 90 days before"),
        Case("document-returns", "documents", ["What is our returns policy for labneh?"], expect_text=["24 hours"],
             source="Returns Policy.pdf", correct="report within 24 hours with a photo"),
        Case("document-delivery-fee", "documents", ["How much is delivery to Zarqa?"], expect=[Decimal("3.5")],
             source="Delivery Policy.pdf", correct="3.500 JOD"),
        Case("company-profile", "company", ["Tell me about my company"], expect_text=["2014"],
             source="Company Profile.pdf + company settings", correct="founded 2014 in Amman"),
        Case("combined-sales-and-competitors", "combined",
             ["How did Extra Virgin Olive Oil 1L sell last month and how does my price compare with competitors?"],
             expect=[evoo_last[0], truth.price(z, "Extra Virgin Olive Oil 1L")],
             source="invoice_items + competitor price tiers",
             correct=f"{evoo_last[0]} units; your price {truth.price(z, 'Extra Virgin Olive Oil 1L')}"),
        Case("missing-period", "missing", ["How much did we sell in March 2024?"], expect_text=["no sales"],
             source="invoices (none in period)", correct="says no sales are recorded and when the records start"),
        Case("missing-customer-names", "missing", ["Who are my top 5 customers this year?"],
             expect_text=["no customer names"], source="invoices.customer_name (empty)",
             correct="says customers can't be ranked; invents no names"),
        Case("market-external", "market", ["What is the average retail price of olive oil in Jordan?"],
             status=("public_research", None), forbid_text=["recorded cost price"], source="public research (web search)",
             correct="researched or reports exactly why research could not run"),
        Case("sales-conversational-comparison", "sales/comparison",
             [f"How were sales in {month_name} compared to {prev_start.strftime('%B')}?"],
             expect=[last_month[0], truth.revenue(z, prev_start, prev_end)[0]], forbid=[rolling30],
             source="invoices (two months)", correct="both months' revenue"),
        Case("sales-arabic-quarters-arabic-digits", "sales/arabic",
             ["مبيعات الربع الثاني ٢٠٢٦ مقارنة بالربع الثاني ٢٠٢٥"] if today.year == 2026 else
             [f"مبيعات الربع الثاني {today.year} مقارنة بالربع الثاني {today.year - 1}"],
             expect=[q2_now[0], q2_before[0]], source="invoices (two quarters)", correct="both quarters' revenue"),
        Case("sales-money-made", "sales", [f"how much money did we make in {month_name.lower()}"],
             expect=[last_month[0]], source="invoices (month)", correct=f"{last_month[0]} JOD"),
        Case("top-units-last-month", "products", ["Which of my products sold the most units last month?"],
             expect_text=[truth.top_product(z, last_start, last_end, by="units")[0]],
             expect=[truth.top_product(z, last_start, last_end, by="units")[1]],
             source="invoice_items (month, by units)", correct="the month's units leader"),
        Case("catalogue-size", "company", ["How many products do I have?"],
             expect=[len(zaytouna_names)], source="products", correct=f"{len(zaytouna_names)} products"),
        Case("market-external-ar", "market/arabic", ["كم متوسط سعر زيت الزيتون في الأردن؟"],
             status=("public_research", None), forbid_text=["recorded cost price", "سعر التكلفة"],
             source="public research", correct="researched, or says why it could not; never their cost prices"),
        Case("tenant-isolation-ar", "isolation/arabic", ["كم كانت مبيعاتنا الشهر الماضي؟"], tenant_email=BYTEFIX,
             expect=[bytefix_last[0]], forbid=[last_month[0]], source="ByteFix invoices only",
             correct=f"ByteFix revenue {bytefix_last[0]}"),
        Case("tenant-isolation", "isolation", ["What were my sales last month?"], tenant_email=BYTEFIX,
             expect=[bytefix_last[0]], forbid=[last_month[0]], forbid_text=zaytouna_names[:12],
             source="ByteFix invoices only", correct=f"ByteFix {month_name} revenue {bytefix_last[0]} EGP"),
    ]
    if staff_email:
        cases += [
            Case("staff-no-revenue", "permissions", ["What was my total revenue last month?"], who=staff_email,
                 forbid=[last_month[0], rolling30], expect_text=["role"], source="none (not permitted)",
                 correct="says the role can't see sales; no revenue figure"),
            Case("staff-stock", "permissions", ["What is the stock level of Medjool Dates 1kg?"], who=staff_email,
                 expect=[truth.stock(z, "Medjool Dates 1kg")], forbid_text=["units sold", "cost price"],
                 source="inventory only", correct="stock shown, no sales pace or cost"),
        ]
    return cases


def build_extended_cases(truth: Truth):
    """Harder paraphrases of the core questions - other wordings, dialects, units and
    period expressions - with the same independent-SQL ground truth. They measure how
    well the assistant generalises beyond the exact phrasings the core cases use."""
    z, b = truth.tenant(ZAYTOUNA), truth.tenant(BYTEFIX)
    today = truth.today(z)
    tomorrow = today + timedelta(days=1)
    last_start, last_end = month_bounds(today, 1)
    prev_start, prev_end = month_bounds(today, 2)
    year = today.year
    q = (today.month - 1) // 3
    lq_start = date(year if q else year - 1, (q - 1) % 4 * 3 + 1, 1)
    lq_end = date(year, q * 3 + 1, 1) if q else date(year, 1, 1)
    sept = (date(year, 9, 1), date(year, 10, 1))
    aug = (date(year, 8, 1), date(year, 9, 1))
    y2025 = (date(year - 1, 1, 1), date(year, 1, 1))
    june_range = (date(year, 6, 1), date(year, 7, 16))
    rev = lambda a, e: truth.revenue(z, a, e)[0]
    units = lambda name, a, e: truth.product_sales(z, name, a, e)[0]
    stock = lambda name: truth.stock(z, name)
    month = last_start.strftime("%B")
    reviews_year = truth.reviews(z, date(year, 1, 1), tomorrow)
    top_q3_rev = truth.top_product(z, date(year, 7, 1), date(year, 10, 1), by="revenue")
    top_last_units = truth.top_product(z, last_start, last_end, by="units")
    top_ytd_rev = truth.top_product(z, date(year, 1, 1), tomorrow, by="revenue")
    C = Case
    return [
        # Sales: other period wordings
        C("x-sales-september", "sales", [f"What was revenue in September {year}?"], expect=[rev(*sept)]),
        C("x-sales-how-did-we-do", "sales", [f"How did we do in August {year}?"], expect=[rev(*aug)]),
        C("x-sales-last-quarter", "sales", ["What were total sales last quarter?"], expect=[rev(lq_start, lq_end)]),
        C("x-sales-year-2025", "sales", [f"Total sales in {year - 1}"], expect=[rev(*y2025)]),
        C("x-sales-range", "sales", [f"Sales between 1 June and 15 July {year}"], expect=[rev(*june_range)]),
        C("x-sales-previous-month", "sales", ["What did we earn the previous month?"], expect=[rev(last_start, last_end)]),
        C("x-sales-turnover", "sales", ["What was our turnover last month?"], expect=[rev(last_start, last_end)]),
        C("x-sales-income", "sales", [f"income for {month.lower()} please"], expect=[rev(last_start, last_end)]),
        C("x-sales-ar-september", "sales/arabic", ["كم بعنا في أيلول؟"], expect=[rev(*sept)]),
        C("x-sales-ar-sept-egy", "sales/arabic", ["مبيعات شهر سبتمبر كانت كام؟"], expect=[rev(*sept)]),
        C("x-sales-ar-last-month", "sales/arabic", ["قديش كانت إيراداتنا الشهر اللي فات؟"], expect=[rev(last_start, last_end)]),
        C("x-sales-ar-q3", "sales/arabic", [f"إيرادات الربع الثالث {year}"], expect=[rev(date(year, 7, 1), date(year, 10, 1))]),
        C("x-sales-ar-year", "sales/arabic", [f"كم مجموع المبيعات في سنة {year - 1}؟"], expect=[rev(*y2025)]),
        C("x-sales-compare-months", "sales/comparison", [f"{month} vs {prev_start.strftime('%B')} revenue"],
          expect=[rev(last_start, last_end), rev(prev_start, prev_end)]),
        C("x-sales-yoy", "sales/comparison", [f"Compare September {year} sales with September {year - 1}"],
          expect=[rev(*sept), rev(date(year - 1, 9, 1), date(year - 1, 10, 1))]),
        # Products
        C("x-units-dates-sept", "products", [f"How many Medjool Dates 1kg did we sell in September {year}?"],
          expect=[units("Medjool Dates 1kg", *sept)]),
        C("x-units-tahini-last-month", "products", ["units of tahini sold last month"],
          expect=[units("Tahini 450g", last_start, last_end)]),
        C("x-units-ar-product", "products/arabic", ["كم علبة طحينة بعنا الشهر الماضي؟"],
          expect=[units("Tahini 450g", last_start, last_end)]),
        C("x-units-ar-honey", "products/arabic", ["كم بعنا من عسل السدر في أيلول؟"], expect=[units("Sidr Honey 500g", *sept)]),
        C("x-best-seller-last-month", "products", ["What was our best seller last month by units?"],
          expect_text=[top_last_units[0]], expect=[top_last_units[1]]),
        C("x-top-revenue-q3", "products", [f"Which product brought in the most revenue in Q3 {year}?"],
          expect_text=[top_q3_rev[0]]),
        C("x-most-popular-ytd", "products", ["What's my best-selling product this year?"], expect_text=[top_ytd_rev[0]]),
        C("x-top-ar", "products/arabic", ["شو أكثر منتج بعناه الشهر الماضي؟"],
          expect_text=[truth.names(z, top_last_units[0])], expect=[top_last_units[1]]),
        # Inventory
        C("x-stock-zaatar", "inventory", ["How much Premium Za'atar Blend 250g do we have left?"],
          expect=[stock("Premium Za'atar Blend 250g")]),
        C("x-stock-dates-partial", "inventory", ["stock of medjool dates"],
          expect=[stock("Medjool Dates 1kg"), stock("Medjool Dates Gift Box 500g")]),
        C("x-stock-ar-honey", "inventory/arabic", ["كم باقي عندنا عسل سدر؟"], expect=[stock("Sidr Honey 500g")]),
        C("x-stock-in-stock", "inventory", ["Do we have Tahini 450g in stock?"], expect=[stock("Tahini 450g")]),
        # Forecast
        C("x-forecast-honey", "forecast", ["What's the expected demand for Sidr Honey 500g?"],
          expect=[truth.forecast(z, "Sidr Honey 500g")]),
        C("x-forecast-will-sell", "forecast", ["How many Tahini 450g will we sell next month?"],
          expect=[truth.forecast(z, "Tahini 450g")]),
        C("x-forecast-ar", "forecast/arabic", ["كم متوقع نبيع من الطحينة الشهر الجاي؟"], expect=[truth.forecast(z, "Tahini 450g")]),
        # Price
        C("x-price-charge", "pricing", ["What do we charge for Tahini 450g?"], expect=[truth.price(z, "Tahini 450g")]),
        C("x-price-ar", "pricing/arabic", ["قديش سعر الطحينة عنا؟"], expect=[truth.price(z, "Tahini 450g")]),
        # Reviews
        C("x-reviews-count-year", "sentiment", ["How many customer reviews did we get this year?"], expect=[reviews_year[0]]),
        C("x-reviews-feedback", "sentiment", ["What's the customer feedback like?"], expect=[truth.reviews(z)[0]], forbid_text=["customs"]),
        # Documents / company
        C("x-doc-delivery-ar", "documents/arabic", ["كم رسوم التوصيل للزرقاء؟"], expect=[Decimal("3.5")]),
        C("x-doc-returns-paraphrase", "documents", ["Can customers return labneh?"], expect_text=["24 hours"]),
        C("x-company-founded", "company", ["When was the company founded?"], expect_text=["2014"]),
        C("x-catalogue-ar", "company/arabic", ["كم منتج عندي؟"], expect=[len([n for n in truth.product_names(z) if n])]),
        # Follow-ups
        C("x-follow-what-about", "follow-up", [f"What was revenue in August {year}?", "what about September?"], expect=[rev(*sept)]),
        C("x-follow-last-year", "follow-up", [f"Sales in September {year}", "and the same month last year?"],
          expect=[rev(date(year - 1, 9, 1), date(year - 1, 10, 1))]),
        C("x-follow-product-month", "follow-up", ["How much Tahini 450g did we sell last month?", "and in September?"],
          expect=[units("Tahini 450g", *sept)]),
        C("x-follow-ar", "follow-up/arabic", ["كم كانت المبيعات في آب؟", "وفي أيلول؟"], expect=[rev(*sept)]),
        # Missing data / isolation
        C("x-missing-2023", "missing", ["What were sales in 2023?"], expect_text=["no sales"]),
        C("x-isolation-bytefix-product", "isolation", ["How much Sidr Honey did we sell last month?"], tenant_email=BYTEFIX,
          forbid=[units("Sidr Honey 500g", last_start, last_end)] if units("Sidr Honey 500g", last_start, last_end) else []),
        C("x-isolation-bytefix-sept", "isolation", [f"What was revenue in September {year}?"], tenant_email=BYTEFIX,
          expect=[truth.revenue(b, *sept)[0]], forbid=[rev(*sept)]),
    ]


def build_holdout_cases(truth: Truth):
    """New wordings kept out of development: written before the run that scores them and never tuned
    against, so their pass rate estimates how the assistant does on questions nobody tested."""
    z, b = truth.tenant(ZAYTOUNA), truth.tenant(BYTEFIX)
    today = truth.today(z)
    tomorrow = today + timedelta(days=1)
    last_start, last_end = month_bounds(today, 1)
    year = today.year
    jul, aug, sep = (date(year, 7, 1), date(year, 8, 1)), (date(year, 8, 1), date(year, 9, 1)), (date(year, 9, 1), date(year, 10, 1))
    rev = lambda a, e: truth.revenue(z, a, e)[0]
    units = lambda name, a, e: truth.product_sales(z, name, a, e)[0]
    top_aug_units = truth.top_product(z, *aug, by="units")
    C = Case
    return [
        C("h-sales-july-short", "sales", [f"july {year} sales?"], expect=[rev(*jul)]),
        C("h-sales-gross-sales", "sales", ["gross sales for last month"], expect=[rev(last_start, last_end)]),
        C("h-sales-how-much-brought", "sales", [f"How much did the shop bring in during September {year}?"], expect=[rev(*sep)]),
        C("h-sales-h1", "sales", [f"Revenue for the first half of {year}"], expect=[rev(date(year, 1, 1), date(year, 7, 1))]),
        C("h-sales-ar-gulf", "sales/arabic", ["كم كان دخلنا في شهر ٩؟"], expect=[rev(*sep)]),
        C("h-sales-ar-msa", "sales/arabic", ["ما إجمالي المبيعات خلال الشهر الماضي؟"], expect=[rev(last_start, last_end)]),
        C("h-sales-ar-july", "sales/arabic", ["مبيعات تموز"], expect=[rev(*jul)]),
        C("h-units-honey-aug", "products", [f"Sidr Honey 500g units in August {year}"], expect=[units("Sidr Honey 500g", *aug)]),
        C("h-units-coffee-partial", "products", ["how many turkish coffee did we sell last month"],
          expect=[units("Turkish Coffee Medium Roast 500g", last_start, last_end)]),
        C("h-units-ar-labneh", "products/arabic", ["كم كيلو لبنة بعنا الشهر الماضي؟"], expect=[units("Fresh Labneh (per kg)", last_start, last_end)]),
        C("h-top-aug", "products", [f"Which item sold the most units in August {year}?"],
          expect_text=[truth.names(z, top_aug_units[0])], expect=[top_aug_units[1]]),
        C("h-top-ar-msa", "products/arabic", ["ما هو المنتج الأكثر مبيعاً هذا العام؟"],
          # "best-selling" may mean by revenue or by units: either leader answers it.
          expect_text=[truth.names(z, truth.top_product(z, date(year, 1, 1), tomorrow, by="revenue")[0])
                       + truth.names(z, truth.top_product(z, date(year, 1, 1), tomorrow, by="units")[0])]),
        C("h-stock-how-many", "inventory", ["How many Sumac 200g are in the warehouse?"], expect=[truth.stock(z, "Sumac 200g")]),
        C("h-stock-ar-msa", "inventory/arabic", ["ما هي الكمية المتوفرة من الطحينة؟"], expect=[truth.stock(z, "Tahini 450g")]),
        C("h-stock-running-low", "inventory", ["Are we running low on Freekeh 1kg?"], expect=[truth.stock(z, "Freekeh 1kg")]),
        C("h-forecast-coming-weeks", "forecast", ["Projected sales of Sumac 200g in the coming month"], expect=[truth.forecast(z, "Sumac 200g")]),
        C("h-forecast-ar-msa", "forecast/arabic", ["ما هو الطلب المتوقع على عسل السدر؟"], expect=[truth.forecast(z, "Sidr Honey 500g")]),
        C("h-price-selling", "pricing", ["What's the selling price of Freekeh 1kg?"], expect=[truth.price(z, "Freekeh 1kg")]),
        C("h-price-ar-gulf", "pricing/arabic", ["بكم نبيع السماق؟"], expect=[truth.price(z, "Sumac 200g")]),
        C("h-reviews-total", "sentiment", ["How many reviews do we have in total?"], expect=[truth.reviews(z)[0]]),
        C("h-doc-refund-ar", "documents/arabic", ["هل يمكن استرجاع اللبنة؟"], expect_text=["24"]),
        C("h-doc-delivery-zarqa-paraphrase", "documents", ["What's the delivery charge for Zarqa?"], expect=[Decimal("3.5")]),
        C("h-follow-ar-product", "follow-up/arabic", ["كم بعنا طحينة في آب؟", "وفي أيلول؟"], expect=[units("Tahini 450g", *sep)]),
        C("h-follow-en-and-revenue", "follow-up", [f"Units of Freekeh 1kg sold in September {year}", "and in August?"],
          expect=[units("Freekeh 1kg", *aug)]),
        C("h-isolation-ar-bytefix", "isolation/arabic", ["كم كانت مبيعاتنا في أيلول؟"], tenant_email=BYTEFIX,
          expect=[truth.revenue(b, *sep)[0]], forbid=[rev(*sep)]),
    ]


def build_holdout2_cases(truth: Truth):
    """A second held-out set, written after the fixes the first one led to and scored once, so the
    generalisation estimate is not inflated by having tuned against it."""
    z, b = truth.tenant(ZAYTOUNA), truth.tenant(BYTEFIX)
    today = truth.today(z)
    tomorrow = today + timedelta(days=1)
    last_start, last_end = month_bounds(today, 1)
    year = today.year
    jun, aug, sep = (date(year, 6, 1), date(year, 7, 1)), (date(year, 8, 1), date(year, 9, 1)), (date(year, 9, 1), date(year, 10, 1))
    rev = lambda a, e: truth.revenue(z, a, e)[0]
    units = lambda name, a, e: truth.product_sales(z, name, a, e)[0]
    top_sep_rev = truth.top_product(z, *sep, by="revenue")
    C = Case
    return [
        C("h2-sales-june-numeric", "sales", [f"sales 06/{year}"], expect=[rev(*jun)]),
        C("h2-sales-what-did-we-take", "sales", ["what did we take in last month"], expect=[rev(last_start, last_end)]),
        C("h2-sales-total-revenue-aug", "sales", [f"total revenue august"], expect=[rev(*aug)]),
        C("h2-sales-ar-levant-sep", "sales/arabic", ["قديش بعنا بشهر أيلول؟"], expect=[rev(*sep)]),
        C("h2-sales-ar-egypt-last", "sales/arabic", ["المبيعات الشهر اللي فات عاملة كام؟"], expect=[rev(last_start, last_end)]),
        C("h2-sales-q3-vs-q2", "sales/comparison", [f"Q3 vs Q2 {year} sales"],
          expect=[rev(date(year, 7, 1), date(year, 10, 1)), rev(date(year, 4, 1), date(year, 7, 1))]),
        C("h2-units-olive-tin-sep", "products", [f"How many Olive Oil Tin 4L did we sell in September?"],
          expect=[units("Olive Oil Tin 4L", *sep)]),
        C("h2-units-ar-freekeh", "products/arabic", ["كم كيس فريكة بعنا في آب؟"], expect=[units("Freekeh 1kg", *aug)]),
        C("h2-top-sep-revenue", "products", [f"Top product by revenue in September {year}"],
          expect_text=[truth.names(z, top_sep_rev[0])]),
        C("h2-stock-maftoul", "inventory", ["Maftoul 500g stock level"], expect=[truth.stock(z, "Maftoul 500g")]),
        C("h2-stock-ar-coffee", "inventory/arabic", ["كم عندي قهوة تركية بالمخزن؟"], expect=[truth.stock(z, "Turkish Coffee Medium Roast 500g")]),
        C("h2-stock-units-available", "inventory", ["How many units of Sumac 200g are available?"], expect=[truth.stock(z, "Sumac 200g")]),
        C("h2-forecast-next-30", "forecast", ["Demand forecast for Maftoul 500g over the next 30 days"],
          expect=[truth.forecast(z, "Maftoul 500g")]),
        C("h2-forecast-ar-dates", "forecast/arabic", ["كم رح نبيع تمر مجهول الشهر الجاي؟"], expect=[truth.forecast(z, "Medjool Dates 1kg")]),
        C("h2-price-how-much-is", "pricing", ["How much is our Maftoul 500g?"], expect=[truth.price(z, "Maftoul 500g")]),
        C("h2-price-ar-msa", "pricing/arabic", ["ما سعر بيع المفتول؟"], expect=[truth.price(z, "Maftoul 500g")]),
        C("h2-reviews-rating", "sentiment", ["what is our average rating?"], expect=[truth.reviews(z)[0]]),
        C("h2-doc-fresh-returns", "documents", ["What's the policy on returning fresh products?"], expect_text=["24 hours"]),
        C("h2-follow-ar-quarter", "follow-up/arabic", ["مبيعات الربع الثالث", "والربع الثاني؟"],
          expect=[rev(date(year, 4, 1), date(year, 7, 1))]),
        C("h2-isolation-bytefix-q3", "isolation", ["Q3 revenue"], tenant_email=BYTEFIX,
          expect=[truth.revenue(b, date(year, 7, 1), date(year, 10, 1))[0]], forbid=[rev(date(year, 7, 1), date(year, 10, 1))]),
    ]


# --- running --------------------------------------------------------------------------

def login(api, email, password, tenant=None):
    body = {"email": email, "password": password, **({"tenant_id": tenant} if tenant else {})}
    response = httpx.post(f"{api}/auth/login", json=body, timeout=60)
    response.raise_for_status()
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def run(case: Case, api, password, truth: Truth):
    email = case.tenant_email if case.who == "owner" else case.who
    tenant = truth.tenant(ZAYTOUNA) if case.who != "owner" else None
    headers = login(api, email, password, tenant)
    session, replies = None, []
    for question in case.questions:
        started = time.time()
        for _attempt in range(4):
            response = httpx.post(f"{api}/rag/query", json={"query_text": question, "session_id": session},
                                  headers=headers, timeout=240)
            if response.status_code != 429:
                break
            # The assistant's own per-company rate limit (AI_REQUESTS_PER_MINUTE): wait as told, then ask again.
            time.sleep(int(response.headers.get("Retry-After", "30")) + 1)
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        session = body.get("session_id", session)
        replies.append({"question": question, "status": response.status_code, "mode": body.get("answer_mode"),
                        "seconds": round(time.time() - started, 1), "answer": body.get("answer", ""),
                        "evidence_status": body.get("evidence_status", []), "references": len(body.get("references", []))})
    last = replies[-1]
    text = last["answer"]
    problems = []
    if last["status"] != 200:
        problems.append(f"HTTP {last['status']}")
    for value in case.expect:
        if not has_number(text, value):
            problems.append(f"missing figure {value}")
    for word in case.expect_text:
        # A tuple is a set of alternatives: a product may be named by its English or its Arabic name.
        options = word if isinstance(word, tuple) else (word,)
        if not any(option and option.lower() in text.lower() for option in options):
            problems.append(f"missing text {options[0]!r}")
    for value in case.forbid:
        if value and has_number(text, value):
            problems.append(f"contains forbidden figure {value}")
    for word in case.forbid_text:
        if word and word.lower() in text.lower():
            problems.append(f"contains forbidden text {word!r}")
    if case.status:
        need, wanted = case.status
        found = [s for s in last["evidence_status"] if s.get("need") == need]
        if not found:
            problems.append(f"no {need} status reported")
    return {"key": case.key, "category": case.category, "source": case.source, "correct": case.correct,
            "passed": not problems, "problems": problems, "turns": replies}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--password", required=True)
    parser.add_argument("--staff-email")
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--report")
    parser.add_argument("--suite", choices=("core", "extended", "holdout", "holdout2", "all"), default="core",
                        help="core: the original cases; extended: harder paraphrases; holdout: wordings never "
                             "tuned against; all: every case")
    args = parser.parse_args()
    truth = Truth(os.environ["DATABASE_URL"].replace("+asyncpg", ""))
    cases = (build_cases(truth, args.staff_email) if args.suite in ("core", "all") else []) + \
            (build_extended_cases(truth) if args.suite in ("extended", "all") else []) + \
            (build_holdout_cases(truth) if args.suite in ("holdout", "all") else []) + \
            (build_holdout2_cases(truth) if args.suite in ("holdout2", "all") else [])
    cases = [c for c in cases if not args.only or c.key in args.only]
    results = []
    for case in cases:
        result = run(case, args.api.rstrip("/"), args.password, truth)
        results.append(result)
        modes = ",".join(str(t["mode"]) for t in result["turns"])
        print(f"{'PASS' if result['passed'] else 'FAIL'} {case.key:34} [{case.category}] mode={modes} "
              f"{'; '.join(result['problems'])}")
    passed = sum(r["passed"] for r in results)
    print(f"\n{passed}/{len(results)} passed")
    if args.report:
        with open(args.report, "w", encoding="utf-8") as handle:
            json.dump(results, handle, ensure_ascii=False, indent=1, default=str)
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
