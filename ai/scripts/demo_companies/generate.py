"""
Deterministic sales-history, competitor and review generator for the demo /
acceptance companies in profiles.py. Writes, per company, the files that
business would really hand over - in its own export format - into
<out_dir>/<company key>/:

  sales_*.csv|xlsx      sales history split by quarter or month, in the
                        company's own header language/delimiter/encoding
  reviews.csv           customer reviews (mixed languages, real dates)
  manifest.json         products, competitors, observed competitor prices,
                        and expected totals so seeded data can be verified

Usage: python -m scripts.demo_companies.generate --out-dir /tmp/demo --end 2026-10-05
"""
import argparse
import csv
import io
import json
import math
import random
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from openpyxl import Workbook

from scripts.demo_companies.profiles import COMPANIES, EID_AL_ADHA, EID_AL_FITR, HISTORY_START, RAMADAN, Company, Product

MINOR_UNITS = {"JOD": 3, "KWD": 3, "BHD": 3, "OMR": 3, "TND": 3}


def money(value: float, currency: str) -> Decimal:
    exponent = Decimal(1).scaleb(-MINOR_UNITS.get(currency, 2))
    return Decimal(str(value)).quantize(exponent, rounding=ROUND_HALF_UP)


def events_on(day: date) -> set:
    events = set()
    if any(start <= day <= end for start, end in RAMADAN):
        events.add("ramadan")
    if any(0 <= (eid - day).days <= 7 for eid in EID_AL_FITR):
        events.add("eid_fitr")
    if any(0 <= (eid - day).days <= 7 for eid in EID_AL_ADHA):
        events.add("eid_adha")
    if (day.month == 10 and day.day >= 15) or day.month in (11, 12):
        events.add("harvest")
    if (day.month == 6 and day.day >= 15) or day.month in (7, 8):
        events.add("summer")
    if day.month in (12, 1, 2):
        events.add("winter")
    if (day.month == 8 and day.day >= 20) or (day.month == 9 and day.day <= 20):
        events.add("back_to_school")
    if day.month == 11 and 20 <= day.day <= 30:
        events.add("black_friday")
    return events


def price_on(product: Product, day: date) -> float:
    current = product.price_history[0][1]
    for effective, price in product.price_history:
        if effective <= day:
            current = price
    return current


def active(product: Product, day: date) -> bool:
    if product.launched and day < product.launched:
        return False
    if product.discontinued and day >= product.discontinued:
        return False
    return day >= product.price_history[0][0]


def expected_units(company: Company, product: Product, day: date) -> float:
    factor = 1.0
    for event in events_on(day):
        factor *= product.seasonal.get(event, 1.0)
    if day.weekday() in company.weekend:
        factor *= company.weekend_factor
    years = (day - HISTORY_START).days / 365.0
    factor *= (1 + company.yearly_growth) ** years
    return product.base_per_day * factor


def line_quantity(rng: random.Random, company: Company, product: Product, units_today: float) -> Decimal:
    if company.key == "petra":                      # B2B: an order is a sizeable share of the day's volume
        mean = max(units_today / 1.6, 1.0)
        raw = rng.gammavariate(2.2, mean / 2.2)
    elif product.unit in ("kg",):
        raw = rng.gammavariate(2.0, 0.35)
    elif product.unit in ("hour",):
        raw = rng.choice([0.5, 1, 1.5, 2, 2, 3, 3.5, 4, 6, 7.5])
    else:
        raw = 1 + (rng.random() < 0.18) + (rng.random() < 0.05)
    if product.fractional:
        step = Decimal("0.05") if product.unit in ("kg",) else Decimal("0.5") if product.unit == "hour" else Decimal("0.01")
        qty = (Decimal(str(raw)) / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step
        return max(qty, step)
    return Decimal(max(1, int(round(raw))))


def generate_sales(company: Company, end: date, rng: random.Random) -> list:
    """Returns sales lines: dict(date, order, product, qty, price, discount, total)."""
    lines = []
    order_seq = 1000
    day = HISTORY_START
    while day <= end:
        if company.key == "beit":  # restaurant POS: one daily summary row per menu item
            for product in company.products:
                if not active(product, day):
                    continue
                units = expected_units(company, product, day)
                if product.fractional:
                    qty = Decimal(str(max(0.0, rng.gauss(units, units * 0.18)))).quantize(Decimal("0.1"))
                else:
                    qty = Decimal(_poisson(rng, units))
                if qty <= 0:
                    continue
                price = money(price_on(product, day), company.currency)
                lines.append({"date": day, "order": f"Z-{day:%Y%m%d}", "product": product, "qty": qty, "price": price,
                              "discount": 0, "total": money(float(qty * price), company.currency)})
            day += timedelta(days=1)
            continue

        weighted = []
        for product in company.products:
            if not active(product, day):
                continue
            units = expected_units(company, product, day)
            if units <= 0:
                continue
            weighted.append((product, units))
        if company.key == "clarity" and day.day == 1:
            for client in ("Lumen Retail SAS", "Atelier Verde", "Groupe Hexa"):
                retainer = next(p for p in company.products if p.name_en.startswith("Accompagnement"))
                order_seq += 1
                price = money(price_on(retainer, day), company.currency)
                lines.append({"date": day, "order": f"F{day:%Y}-{order_seq}", "product": retainer, "qty": Decimal(1),
                              "price": price, "discount": 0, "total": price})
        total_units = sum(units for _, units in weighted)
        if total_units > 0:
            avg_lines = (company.lines_per_receipt[0] + company.lines_per_receipt[1]) / 2
            expected_lines = sum(units / (1.25 if company.key != "petra" else max(units / 1.6, 1.0)) for _, units in weighted)
            receipts = _poisson(rng, expected_lines / avg_lines)
            products, weights = zip(*weighted)
            units_by_name = {product.name_en: units for product, units in weighted}
            for _ in range(receipts):
                order_seq += 1
                order = f"{company.key[:2].upper()}-{order_seq}"
                count = rng.randint(*company.lines_per_receipt)
                chosen = set()
                for _ in range(count):
                    product = rng.choices(products, weights=weights)[0]
                    if product.name_en in chosen:
                        continue
                    chosen.add(product.name_en)
                    units_today = units_by_name[product.name_en]
                    qty = line_quantity(rng, company, product, units_today)
                    price = money(price_on(product, day), company.currency)
                    discount = 0
                    if rng.random() < company.discount_rate:
                        discount = rng.choice(company.discount_pcts)
                    if company.key == "zaytouna" and "ramadan" in events_on(day) and product.category == "Dates":
                        discount = 10  # the store's real Ramadan dates promotion
                    gross = qty * price
                    total = money(float(gross * (100 - discount) / 100), company.currency)
                    lines.append({"date": day, "order": order, "product": product, "qty": qty, "price": price,
                                  "discount": discount, "total": total})
        day += timedelta(days=1)
    return lines


def _poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 60:
        return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))
    threshold, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= threshold:
            return k
        k += 1


# ---- export formats --------------------------------------------------------

def _period_key(day: date, period: str) -> str:
    return f"{day.year}-Q{(day.month - 1) // 3 + 1}" if period == "quarter" else f"{day:%Y-%m}"


def _num(value: Decimal, decimal_comma: bool) -> str:
    text = format(value.normalize(), "f") if value == value.to_integral() else format(value, "f").rstrip("0").rstrip(".")
    return text.replace(".", ",") if decimal_comma else text


def write_exports(company: Company, lines: list, out_dir: Path) -> list:
    by_period = defaultdict(list)
    for line in lines:
        by_period[_period_key(line["date"], company.export_period)].append(line)
    files = []
    for period, rows in sorted(by_period.items()):
        fmt = company.export_format
        if fmt == "csv_en":
            path = out_dir / f"sales_{period}.csv"
            with open(path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["Date", "Order ID", "Product", "Quantity", "Unit Price", "Currency", "Discount %", "Line Total"])
                for r in rows:
                    writer.writerow([r["date"].isoformat(), r["order"], r["product"].name_en, _num(r["qty"], False), str(r["price"]),
                                     company.currency, r["discount"], str(r["total"])])
        elif fmt == "csv_fr_semicolon":
            path = out_dir / f"ventes_{period}.csv"
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(["Date", "N° facture", "Produit", "Quantité", "Prix unitaire", "Devise", "Remise %", "Montant TTC"])
                for r in rows:
                    writer.writerow([r["date"].strftime("%d/%m/%Y"), r["order"], r["product"].name_en, _num(r["qty"], True),
                                     _num(r["price"], True), company.currency, r["discount"], _num(r["total"], True)])
        elif fmt == "csv_ar_cp1256":
            path = out_dir / f"sales_{period}.csv"
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(["التاريخ", "رقم الفاتورة", "اسم الصنف", "الكمية", "سعر الوحدة", "العملة", "نسبة الخصم", "الصافي"])
            for r in rows:
                writer.writerow([r["date"].strftime("%d/%m/%Y"), r["order"], r["product"].name_local or r["product"].name_en,
                                 _num(r["qty"], False), str(r["price"]), company.currency, r["discount"], str(r["total"])])
            path.write_bytes(buffer.getvalue().encode("cp1256"))
        elif fmt in ("xlsx_en", "xlsx_en_erp", "xlsx_ar_daily_summary"):
            path = out_dir / f"sales_{period}.xlsx"
            wb = Workbook()
            ws = wb.active
            if fmt == "xlsx_en":
                ws.title = "Sales"
                ws.append(["Invoice Date", "Invoice No", "Item", "Qty", "Price", "Currency", "Disc %", "Net Amount"])
                for r in rows:
                    ws.append([r["date"], r["order"], r["product"].name_en, float(r["qty"]), float(r["price"]), company.currency,
                               r["discount"], float(r["total"])])
            elif fmt == "xlsx_en_erp":
                ws.title = "Sales Lines"
                ws.append(["Posting Date", "Document No.", "Description", "Quantity", "Unit Price Excl. VAT", "Currency Code",
                           "Line Discount %", "Line Amount"])
                for r in rows:
                    ws.append([r["date"], r["order"], r["product"].name_en, float(r["qty"]), float(r["price"]), company.currency,
                               r["discount"], float(r["total"])])
            else:
                ws.title = "تقرير مبيعات الأصناف"
                ws.append(["التاريخ", "الصنف", "الكمية المباعة", "سعر الوحدة", "العملة", "الإجمالي"])
                for r in rows:
                    ws.append([r["date"], r["product"].name_local or r["product"].name_en, float(r["qty"]), float(r["price"]),
                               company.currency, float(r["total"])])
            wb.save(path)
        else:
            raise ValueError(fmt)
        files.append(path.name)
    return files


# ---- reviews -----------------------------------------------------------------

REVIEW_TEXT = {
    "en": {
        "positive": ["Excellent quality, exactly as described. Will order again.", "Fast delivery and very friendly staff.",
                     "Best {p} I've had in a long time.", "Great value for money, highly recommended.",
                     "Lovely experience, everything was perfect.", "Really impressed with the {p}. Fresh and well packed."],
        "neutral": ["The {p} was fine, nothing special.", "Average experience, delivery took a bit longer than promised.",
                    "Okay overall. Prices are a little high but quality is decent."],
        "negative": ["Very disappointed - the {p} arrived damaged.", "Waited 40 minutes and nobody answered the phone.",
                     "Prices went up a lot recently, not worth it anymore.", "The order was incomplete and support never replied.",
                     "Poor quality this time, the {p} was not fresh."],
        "mixed": ["Good {p} but the delivery was late.", "Staff were lovely, but the {p} was smaller than expected."],
    },
    "ar": {
        "positive": ["جودة ممتازة والتوصيل سريع، أنصح فيهم", "{p} طازج وطعمه رائع، شكراً لكم", "خدمة راقية وتعامل محترم جداً",
                     "أفضل {p} جربته، رح أطلب مرة ثانية", "تغليف أنيق والأسعار مناسبة"],
        "neutral": ["{p} عادي، لا بأس به", "التجربة مقبولة لكن التوصيل تأخر شوي"],
        "negative": ["الطلب وصل ناقص وما حدا رد على التلفون", "{p} ما كان طازج هالمرة، خيبة أمل", "الأسعار صارت غالية كتير",
                     "انتظرت ساعة وما وصل الطلب، تجربة سيئة"],
        "mixed": ["{p} ممتاز بس السعر صار أغلى من قبل", "الموظفين لطيفين بس الانتظار كان طويل"],
    },
    "fr": {
        "positive": ["Qualité excellente, je recommande vivement.", "Accueil chaleureux et conseils précieux.",
                     "Le {p} est magnifique, finitions impeccables.", "Livraison rapide et emballage soigné."],
        "neutral": ["Le {p} est correct, sans plus.", "Service correct mais un peu d'attente."],
        "negative": ["Très déçue, le {p} ne correspond pas aux photos.", "Délai de livraison non respecté et aucune réponse.",
                     "Prix trop élevés pour la qualité proposée."],
        "mixed": ["Joli {p} mais la taille est petite.", "Bon conseil mais les prix ont beaucoup augmenté."],
    },
}

PLATFORMS = ["Google Maps", "Facebook", "Instagram", "Website", "WhatsApp survey"]
NAMES = {"en": ["Lina K.", "Omar S.", "Sam", "Nadia R.", "Yousef", "Maria", "Chris P."],
         "ar": ["أبو محمد", "رنا", "سلمى", "أم خالد", "محمود", "نور", "فراس"],
         "fr": ["Claire D.", "Karim B.", "Sophie", "Yasmine", "Marc L."]}


def generate_reviews(company: Company, end: date, rng: random.Random) -> list:
    reviews = []
    month = date(HISTORY_START.year, HISTORY_START.month, 1)
    while month <= end:
        for _ in range(_poisson(rng, company.reviews_per_month)):
            day = month + timedelta(days=rng.randint(0, 27))
            if day > end:
                continue
            language = rng.choices(list(company.review_language_mix), weights=list(company.review_language_mix.values()))[0]
            # a rough patch: summer 2025 delivery problems for the retailer, price rises for the electronics shop
            bad_period = (company.key == "zaytouna" and day.month in (7, 8) and day.year == 2025) or \
                         (company.key == "bytefix" and day >= date(2026, 1, 1))
            weights = [0.62, 0.14, 0.14, 0.10] if not bad_period else [0.35, 0.15, 0.38, 0.12]
            tone = rng.choices(["positive", "neutral", "negative", "mixed"], weights=weights)[0]
            product = rng.choice([p for p in company.products if active(p, day)]) if rng.random() < 0.6 else None
            label = (product.name_local if language == "ar" and product and product.name_local else product.name_en) if product else \
                {"en": "order", "ar": "الطلب", "fr": "produit"}[language]
            text = rng.choice(REVIEW_TEXT[language][tone]).format(p=label)
            rating = {"positive": rng.choice([5, 5, 4]), "neutral": 3, "negative": rng.choice([1, 2]), "mixed": rng.choice([3, 4])}[tone]
            reviews.append({"date": day.isoformat(), "rating": rating, "review": text,
                            "product": product.name_en if product else "", "platform": rng.choice(PLATFORMS),
                            "customer": rng.choice(NAMES[language]), "_tone": tone})
        month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    return reviews


def write_reviews(reviews: list, out_dir: Path) -> str:
    path = out_dir / "reviews.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "rating", "review", "product", "platform", "customer"])
        writer.writeheader()
        for review in reviews:
            writer.writerow({k: v for k, v in review.items() if not k.startswith("_")})
    return path.name


def build(out_dir: Path, end: date, only: set = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {}
    for index, company in enumerate(COMPANIES):
        if only and company.key not in only:
            continue
        rng = random.Random(2026_10_06 + index)
        company_dir = out_dir / company.key
        company_dir.mkdir(exist_ok=True)
        lines = generate_sales(company, end, rng)
        files = write_exports(company, lines, company_dir)
        reviews = generate_reviews(company, end, rng)
        reviews_file = write_reviews(reviews, company_dir)
        totals = defaultdict(lambda: {"units": Decimal(0), "revenue": Decimal(0)})
        for line in lines:
            key = line["product"].name_en
            totals[key]["units"] += line["qty"]
            totals[key]["revenue"] += line["total"]
        manifest = {
            "company": company.business_name, "currency": company.currency, "end": end.isoformat(),
            "sales_files": files, "reviews_file": reviews_file, "line_count": len(lines),
            "order_count": len({line["order"] for line in lines}),
            "revenue_total": str(sum(line["total"] for line in lines)),
            "per_product": {k: {"units": str(v["units"]), "revenue": str(v["revenue"])} for k, v in sorted(totals.items())},
            "daily_revenue": {d: str(v) for d, v in sorted(_daily(lines).items())},
            "review_count": len(reviews),
            "review_tones": {t: sum(1 for r in reviews if r["_tone"] == t) for t in ("positive", "neutral", "negative", "mixed")},
        }
        (company_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
        summary[company.key] = {k: manifest[k] for k in ("line_count", "order_count", "revenue_total", "review_count")}
    return summary


def _daily(lines):
    daily = defaultdict(Decimal)
    for line in lines:
        daily[line["date"].isoformat()] += line["total"]
    return daily


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--end", default=(date.today() - timedelta(days=1)).isoformat())
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args()
    summary = build(Path(args.out_dir), date.fromisoformat(args.end), set(args.only or []))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
