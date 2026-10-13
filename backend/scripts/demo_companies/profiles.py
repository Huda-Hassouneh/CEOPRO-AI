"""
Seven realistic, internally consistent demo/acceptance companies across
materially different business types, countries, currencies, languages and
data shapes. Used only to validate and demonstrate the product - nothing in
the application reads or depends on this module.

Every company's history is generated deterministically (fixed seed) from
explicit business assumptions: per-product base demand, price history,
launch/discontinuation dates, weekday shape for the country's own weekend,
seasonal events (Ramadan, Eid, summer, back-to-school, Black Friday,
olive harvest...), a growth trend, and how that business exports its sales
(header language, delimiter, decimal mark, encoding, file format).
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

HISTORY_START = date(2025, 4, 1)

# Islamic calendar dates (approximate civil dates, Amman/Riyadh observance)
RAMADAN = [(date(2026, 2, 18), date(2026, 3, 19))]
EID_AL_FITR = [date(2026, 3, 20)]
EID_AL_ADHA = [date(2025, 6, 6), date(2026, 5, 27)]


@dataclass
class Product:
    name_en: str
    name_local: Optional[str]
    category: str
    unit: str                       # pcs, kg, m, hour, session, plate...
    price_history: List[Tuple[date, float]]  # (effective from, price)
    cost: Optional[float]
    base_per_day: float             # expected units per day at full season
    stock: Optional[float] = None   # None = stock not tracked (services, made to order)
    fractional: bool = False        # sold by weight/length/time
    launched: Optional[date] = None
    discontinued: Optional[date] = None
    seasonal: Dict[str, float] = field(default_factory=dict)  # event -> demand multiplier
    brand: Optional[str] = None


@dataclass
class Competitor:
    name: str
    website: str
    # product name -> list of (days before today, observed price)
    observed_prices: Dict[str, List[Tuple[int, float]]] = field(default_factory=dict)
    # MARKET: competes with the whole business; PRODUCT: only on these products.
    level: Optional[str] = None


@dataclass
class Company:
    key: str
    business_name: str
    owner_name: str
    email_local: str
    country: str
    currency: str
    business_type: str
    language: str                   # en / ar / fr - how the owner writes
    target_markets: List[dict]
    products: List[Product]
    competitors: List[Competitor]
    receipts_per_day: float         # transactions per day (B2B: invoices per day)
    lines_per_receipt: Tuple[int, int]
    weekend: Tuple[int, ...]        # Monday=0
    weekend_factor: float           # demand on weekend days vs weekdays
    yearly_growth: float            # demand trend per year
    export_format: str              # csv_en / csv_fr_semicolon / xlsx_ar_cp / csv_ar_cp1256 / xlsx_en
    export_period: str              # quarter / month
    discount_rate: float = 0.0      # share of lines with a discount
    discount_pcts: Tuple[int, ...] = (5, 10)
    review_language_mix: Dict[str, float] = field(default_factory=lambda: {"en": 1.0})
    reviews_per_month: int = 10
    documents: List[str] = field(default_factory=list)
    # Where the business is and what kind it is, for the market scan.
    industry_key: Optional[str] = None
    city: Optional[str] = None
    location: Optional[Tuple[float, float]] = None


def _p(*pairs):
    return [(date.fromisoformat(d), price) for d, price in pairs]


ZAYTOUNA = Company(
    key="zaytouna",
    industry_key="supermarket", city="Amman", location=(31.9466, 35.884),
    business_name="Zaytouna Fine Foods",
    owner_name="Rania Haddad",
    email_local="rania",
    country="JO",
    currency="JOD",
    business_type="Specialty food & grocery retailer (2 stores in Amman + online delivery)",
    language="en",
    target_markets=[{"market_type": "COUNTRY", "country_code": "JO"}, {"market_type": "COUNTRY", "country_code": "SA"}, {"market_type": "COUNTRY", "country_code": "AE"}],
    receipts_per_day=34, lines_per_receipt=(1, 4), weekend=(4, 5), weekend_factor=1.35, yearly_growth=0.12,
    export_format="csv_en", export_period="quarter", discount_rate=0.08, discount_pcts=(5, 10, 15),
    review_language_mix={"ar": 0.55, "en": 0.45}, reviews_per_month=14,
    documents=["company_profile", "returns_policy", "delivery_policy", "wholesale_terms", "supplier_price_list"],
    products=[
        Product("Extra Virgin Olive Oil 1L", "زيت زيتون بكر ممتاز 1 لتر", "Olive Oil", "pcs", _p(("2025-04-01", 8.950), ("2026-01-10", 9.500)), 6.200, 9.0, stock=140, seasonal={"harvest": 1.6, "ramadan": 1.2}, brand="Zaytouna"),
        Product("Extra Virgin Olive Oil 500ml", "زيت زيتون بكر ممتاز 500 مل", "Olive Oil", "pcs", _p(("2025-04-01", 5.250), ("2026-01-10", 5.750)), 3.600, 7.0, stock=210, seasonal={"harvest": 1.5}, brand="Zaytouna"),
        Product("Early Harvest Olive Oil 750ml", "زيت زيتون قطفة أولى 750 مل", "Olive Oil", "pcs", _p(("2025-11-01", 12.500)), 8.100, 3.0, stock=60, launched=date(2025, 11, 1), seasonal={"harvest": 2.2}, brand="Zaytouna"),
        Product("Olive Oil Tin 4L", "تنكة زيت زيتون 4 لتر", "Olive Oil", "pcs", _p(("2025-04-01", 31.000), ("2026-01-10", 33.000)), 22.000, 0.9, stock=25, seasonal={"harvest": 3.0}, brand="Zaytouna"),
        Product("Premium Za'atar Blend 250g", "زعتر بلدي ممتاز 250 غرام", "Spices", "pcs", _p(("2025-04-01", 3.250)), 1.400, 11.0, stock=320, seasonal={"ramadan": 1.3}, brand="Zaytouna"),
        Product("Loose Za'atar (per kg)", "زعتر فرط (كيلو)", "Spices", "kg", _p(("2025-04-01", 9.800)), 4.500, 3.2, stock=45.5, fractional=True, seasonal={"ramadan": 1.4}, brand="Zaytouna"),
        Product("Sumac 200g", "سماق 200 غرام", "Spices", "pcs", _p(("2025-04-01", 2.400), ("2026-03-01", 2.600)), 0.950, 5.0, stock=180, brand="Zaytouna"),
        Product("Seven Spices Mix 150g", "بهارات سبعة 150 غرام", "Spices", "pcs", _p(("2025-04-01", 2.100)), 0.850, 4.0, stock=150, seasonal={"ramadan": 1.5, "eid_adha": 1.4}, brand="Zaytouna"),
        Product("Medjool Dates 1kg", "تمر مجهول 1 كيلو", "Dates", "pcs", _p(("2025-04-01", 7.900)), 4.800, 4.5, stock=95, seasonal={"ramadan": 3.5, "eid_fitr": 2.0}, brand="Jordan Valley"),
        Product("Medjool Dates Gift Box 500g", "علبة هدايا تمر مجهول 500 غرام", "Dates", "pcs", _p(("2025-04-01", 6.500)), 3.400, 1.5, stock=70, seasonal={"ramadan": 5.0, "eid_fitr": 3.0, "eid_adha": 2.0}, brand="Jordan Valley"),
        Product("Sidr Honey 500g", "عسل سدر 500 غرام", "Honey", "pcs", _p(("2025-04-01", 18.000), ("2025-12-01", 19.500)), 12.500, 1.8, stock=40, seasonal={"winter": 1.4}, brand="Ajloun Apiaries"),
        Product("Wildflower Honey 1kg", "عسل زهور برية 1 كيلو", "Honey", "pcs", _p(("2025-04-01", 14.000)), 9.000, 1.5, stock=35, seasonal={"winter": 1.3}),
        Product("Fresh Labneh (per kg)", "لبنة طازجة (كيلو)", "Dairy", "kg", _p(("2025-04-01", 4.200), ("2026-02-01", 4.500)), 2.600, 6.5, stock=None, fractional=True, seasonal={"ramadan": 1.4, "summer": 0.85}),
        Product("Nabulsi Cheese 500g", "جبنة نابلسية 500 غرام", "Dairy", "pcs", _p(("2025-04-01", 4.750)), 3.000, 4.0, stock=None, seasonal={"ramadan": 1.6}),
        Product("Freekeh 1kg", "فريكة 1 كيلو", "Grains", "pcs", _p(("2025-04-01", 3.900)), 2.200, 2.5, stock=120, seasonal={"ramadan": 1.8, "winter": 1.3}),
        Product("Coarse Bulgur 1kg", "برغل خشن 1 كيلو", "Grains", "pcs", _p(("2025-04-01", 1.450)), 0.750, 4.0, stock=200),
        Product("Arabic Coffee with Cardamom 250g", "قهوة عربية بالهيل 250 غرام", "Coffee", "pcs", _p(("2025-04-01", 4.500), ("2025-10-01", 4.950)), 2.700, 5.5, stock=160, seasonal={"ramadan": 1.5, "eid_fitr": 2.0, "eid_adha": 1.7}),
        Product("Turkish Coffee Medium Roast 500g", "قهوة تركية تحميص وسط 500 غرام", "Coffee", "pcs", _p(("2025-04-01", 6.250)), 4.000, 3.0, stock=90),
        Product("Qamar al-Din Apricot Paste 400g", "قمر الدين 400 غرام", "Ramadan Specials", "pcs", _p(("2025-04-01", 2.750)), 1.500, 0.3, stock=150, seasonal={"ramadan": 25.0}),
        Product("Tahini 450g", "طحينة 450 غرام", "Pantry", "pcs", _p(("2025-04-01", 2.950)), 1.700, 4.5, stock=140, seasonal={"ramadan": 1.3}),
        Product("Pomegranate Molasses 300ml", "دبس رمان 300 مل", "Pantry", "pcs", _p(("2025-04-01", 3.400)), 1.900, 2.2, stock=110),
        Product("Green Olives Jar 650g", "زيتون أخضر مرصوص 650 غرام", "Olives", "pcs", _p(("2025-04-01", 3.600)), 2.000, 4.0, stock=130, seasonal={"harvest": 1.3}),
        Product("Black Olives Jar 650g", "زيتون أسود 650 غرام", "Olives", "pcs", _p(("2025-04-01", 3.750)), 2.150, 2.5, stock=100),
        Product("Maftoul 500g", "مفتول 500 غرام", "Grains", "pcs", _p(("2025-04-01", 2.300)), 1.200, 1.6, stock=80, seasonal={"winter": 1.5}),
        Product("Nabulsi Olive Oil Soap 6-pack", "صابون زيت زيتون نابلسي 6 قطع", "Home & Gifts", "pcs", _p(("2025-04-01", 5.500)), 2.900, 1.4, stock=75, seasonal={"eid_fitr": 1.8, "eid_adha": 1.5}),
        Product("Ramadan Gift Hamper", "سلة رمضان", "Home & Gifts", "pcs", _p(("2026-02-01", 39.000)), 26.000, 0.1, stock=None, launched=date(2026, 2, 1), seasonal={"ramadan": 40.0, "eid_fitr": 10.0}),
        Product("Hibiscus (Karkadeh) 200g", "كركديه 200 غرام", "Drinks", "pcs", _p(("2025-04-01", 1.900)), 0.900, 1.5, stock=90, seasonal={"summer": 2.0, "ramadan": 2.5}),
        Product("Tamarind Drink Concentrate 1L", "شراب تمر هندي 1 لتر", "Drinks", "pcs", _p(("2025-04-01", 2.600)), 1.300, 0.8, stock=60, discontinued=date(2026, 6, 1), seasonal={"summer": 2.2, "ramadan": 3.0}),
    ],
    competitors=[
        # Market-wide: other grocers and delis competing for the same shoppers.
        Competitor("Al-Bustan Organic Market", "https://albustan-organic.example.jo", {
            "Extra Virgin Olive Oil 1L": [(80, 8.750), (45, 8.900), (12, 8.400), (3, 8.250)],
            "Premium Za'atar Blend 250g": [(40, 3.500), (5, 3.450)],
            "Medjool Dates 1kg": [(30, 8.250), (4, 8.500)],
            "Sidr Honey 500g": [(20, 21.000)],
            "Wildflower Honey 1kg": [(22, 15.500)],
            "Freekeh 1kg": [(18, 4.400)],
            "Tahini 450g": [(16, 3.100)],
        }, level="MARKET"),
        Competitor("Souq Al-Balad Delicatessen", "https://souqalbalad-deli.example.jo", {
            "Extra Virgin Olive Oil 1L": [(25, 9.750), (2, 9.900)],
            "Sumac 200g": [(18, 2.250)],
            "Arabic Coffee with Cardamom 250g": [(10, 4.750)],
            "Tahini 450g": [(9, 3.200)],
            "Fresh Labneh (per kg)": [(12, 4.300)],
            "Nabulsi Cheese 500g": [(12, 4.950)],
            "Green Olives Jar 650g": [(14, 3.450)],
        }, level="MARKET"),
        Competitor("Carrefour Jordan (Taj Mall)", "https://carrefour-taj.example.jo", {
            "Extra Virgin Olive Oil 500ml": [(15, 4.950)],
            "Coarse Bulgur 1kg": [(15, 1.250)],
            "Tahini 450g": [(15, 2.750)],
            "Medjool Dates 1kg": [(6, 7.250)],
            "Turkish Coffee Medium Roast 500g": [(15, 5.950)],
            "Black Olives Jar 650g": [(15, 3.300)],
            "Green Olives Jar 650g": [(15, 3.150)],
            "Pomegranate Molasses 300ml": [(15, 2.950)],
            "Hibiscus (Karkadeh) 200g": [(15, 1.650)],
        }, level="MARKET"),
        Competitor("Beit Al-Mouneh Online", "https://beitalmouneh.example.com", {
            "Freekeh 1kg": [(14, 4.250)],
            "Maftoul 500g": [(14, 2.500)],
            "Pomegranate Molasses 300ml": [(14, 3.250)],
            "Seven Spices Mix 150g": [(14, 2.250)],
            "Olive Oil Tin 4L": [(20, 31.500), (6, 32.000)],
        }, level="MARKET"),
        # Product-level: specialists that compete on particular products only.
        Competitor("Jordan Valley Dates Co.", "https://jvdates.example.jo", {
            "Medjool Dates 1kg": [(60, 7.500), (8, 7.750)],
            "Medjool Dates Gift Box 500g": [(8, 6.000)],
        }, level="PRODUCT"),
        Competitor("Hail Coffee Roasters", "https://hail-roasters.example.jo", {
            "Arabic Coffee with Cardamom 250g": [(35, 5.250), (7, 5.500)],
            "Turkish Coffee Medium Roast 500g": [(35, 6.900), (7, 6.750)],
        }, level="PRODUCT"),
        Competitor("Al-Ameed Coffee House", "https://alameed-coffee.example.jo", {
            "Arabic Coffee with Cardamom 250g": [(20, 4.600), (3, 4.400)],
            "Turkish Coffee Medium Roast 500g": [(20, 5.900)],
        }, level="PRODUCT"),
        Competitor("Ajloun Honey House", "https://ajloun-honey.example.jo", {
            "Sidr Honey 500g": [(30, 17.500), (9, 18.250)],
            "Wildflower Honey 1kg": [(30, 13.250)],
        }, level="PRODUCT"),
        Competitor("Dibeen Olive Press", "https://dibeen-press.example.jo", {
            "Extra Virgin Olive Oil 1L": [(28, 8.950)],
            "Early Harvest Olive Oil 750ml": [(28, 11.500), (5, 11.900)],
            "Olive Oil Tin 4L": [(28, 29.500)],
            "Nabulsi Olive Oil Soap 6-pack": [(28, 5.250)],
        }, level="PRODUCT"),
        Competitor("Spice Route Attarin", "https://spiceroute-attarin.example.jo", {
            "Premium Za'atar Blend 250g": [(24, 3.100)],
            "Loose Za'atar (per kg)": [(24, 8.900), (4, 9.250)],
            "Sumac 200g": [(24, 2.300)],
            "Seven Spices Mix 150g": [(24, 1.950)],
        }, level="PRODUCT"),
        Competitor("Ramadan Bazaar Amman", "https://ramadan-bazaar.example.jo", {
            "Qamar al-Din Apricot Paste 400g": [(200, 2.500)],
            "Ramadan Gift Hamper": [(200, 35.000)],
            "Medjool Dates Gift Box 500g": [(200, 5.750)],
            "Tamarind Drink Concentrate 1L": [(200, 2.250)],
        }, level="PRODUCT"),
    ],
)

ATLAS = Company(
    key="atlas",
    industry_key="fashion", city="Casablanca", location=(33.5883, -7.6324),
    business_name="Atlas Couture",
    owner_name="Salma Idrissi",
    email_local="salma",
    country="MA",
    currency="MAD",
    business_type="Boutique de mode femme (prêt-à-porter et caftans)",
    language="fr",
    target_markets=[{"market_type": "COUNTRY", "country_code": "MA"}, {"market_type": "COUNTRY", "country_code": "FR"}],
    receipts_per_day=9, lines_per_receipt=(1, 3), weekend=(5, 6), weekend_factor=1.6, yearly_growth=0.18,
    export_format="csv_fr_semicolon", export_period="quarter", discount_rate=0.14, discount_pcts=(10, 20, 30),
    review_language_mix={"fr": 0.7, "ar": 0.2, "en": 0.1}, reviews_per_month=6,
    documents=["fashion_returns", "fashion_size_guide"],
    products=[
        Product(f"Robe en lin {color} - Taille {size}", None, "Robes", "pcs", _p(("2025-04-01", 549.0), ("2025-09-15", 499.0)), 210.0, base, stock=stock, seasonal={"summer": 1.8, "winter": 0.4})
        for color, size, base, stock in [("Blanc", "S", 0.25, 12), ("Blanc", "M", 0.35, 15), ("Blanc", "L", 0.22, 10), ("Sable", "M", 0.3, 14), ("Sable", "L", 0.18, 8)]
    ] + [
        Product(f"Caftan brodé {name} - Taille {size}", None, "Caftans", "pcs", _p(("2025-04-01", price)), price * 0.45, base, stock=stock, seasonal={"eid_fitr": 4.0, "eid_adha": 3.0, "ramadan": 1.6, "summer": 1.4})
        for name, size, price, base, stock in [("Émeraude", "M", 1890.0, 0.12, 6), ("Émeraude", "L", 1890.0, 0.08, 4), ("Bordeaux", "M", 2150.0, 0.09, 5), ("Ivoire mariage", "Unique", 4800.0, 0.025, 2)]
    ] + [
        Product("Djellaba laine - Taille M", None, "Djellabas", "pcs", _p(("2025-04-01", 890.0)), 390.0, 0.14, stock=9, seasonal={"winter": 2.5, "summer": 0.3}),
        Product("Djellaba laine - Taille L", None, "Djellabas", "pcs", _p(("2025-04-01", 890.0)), 390.0, 0.1, stock=7, seasonal={"winter": 2.5, "summer": 0.3}),
        Product("Pantalon fluide noir - Taille 38", None, "Pantalons", "pcs", _p(("2025-04-01", 349.0)), 140.0, 0.3, stock=18),
        Product("Pantalon fluide noir - Taille 40", None, "Pantalons", "pcs", _p(("2025-04-01", 349.0)), 140.0, 0.28, stock=16),
        Product("Foulard en soie imprimé", None, "Accessoires", "pcs", _p(("2025-04-01", 229.0)), 75.0, 0.55, stock=40, seasonal={"eid_fitr": 2.0}),
        Product("Babouches cuir - Pointure 38", None, "Chaussures", "pcs", _p(("2025-04-01", 279.0), ("2026-01-01", 299.0)), 110.0, 0.2, stock=12),
        Product("Sac cabas en cuir", None, "Accessoires", "pcs", _p(("2025-10-01", 690.0)), 260.0, 0.15, stock=10, launched=date(2025, 10, 1)),
        Product("Retouche et ourlet", None, "Services", "service", _p(("2025-04-01", 60.0)), None, 0.4, stock=None),
    ],
    competitors=[
        Competitor("Maison Zellige Casablanca", "https://maisonzellige.example.ma", {
            "Robe en lin Blanc - Taille M": [(20, 590.0)],
            "Caftan brodé Émeraude - Taille M": [(12, 2100.0)],
        }),
        Competitor("Kaftan Lux Rabat", "https://kaftanlux.example.ma", {
            "Caftan brodé Émeraude - Taille M": [(30, 1750.0), (6, 1690.0)],
            "Caftan brodé Bordeaux - Taille M": [(6, 1990.0)],
        }),
    ],
)

BEIT_SHAWARMA = Company(
    key="beit",
    industry_key="restaurant", city="Dubai", location=(25.1124, 55.2001),
    business_name="Beit Al Shawarma",
    owner_name="Khaled Mansour",
    email_local="khaled",
    country="AE",
    currency="AED",
    business_type="Restaurant - Levantine shawarma & grill (dine-in, takeaway, delivery apps)",
    language="ar",
    target_markets=[{"market_type": "COUNTRY", "country_code": "AE"}],
    receipts_per_day=0, lines_per_receipt=(1, 1), weekend=(5, 6), weekend_factor=1.3, yearly_growth=0.08,
    export_format="xlsx_ar_daily_summary", export_period="month",
    review_language_mix={"ar": 0.5, "en": 0.5}, reviews_per_month=22,
    documents=["restaurant_menu_allergens"],
    products=[
        Product("Chicken Shawarma Sandwich", "ساندويش شاورما دجاج", "Sandwiches", "pcs", _p(("2025-04-01", 14.0), ("2026-01-01", 15.0)), 5.2, 95, seasonal={"ramadan": 1.3}),
        Product("Beef Shawarma Sandwich", "ساندويش شاورما لحم", "Sandwiches", "pcs", _p(("2025-04-01", 18.0), ("2026-01-01", 19.0)), 7.4, 48, seasonal={"ramadan": 1.2}),
        Product("Chicken Shawarma Plate", "صحن شاورما دجاج", "Plates", "pcs", _p(("2025-04-01", 32.0)), 12.0, 34, seasonal={"ramadan": 1.6}),
        Product("Mixed Grill Platter", "مشاوي مشكلة", "Grill", "pcs", _p(("2025-04-01", 68.0), ("2026-01-01", 72.0)), 31.0, 11, seasonal={"ramadan": 2.4, "eid_fitr": 2.0, "eid_adha": 1.8}),
        Product("Grilled Chicken (per kg)", "دجاج مشوي (كيلو)", "Grill", "kg", _p(("2025-04-01", 54.0)), 21.0, 9.5, fractional=True, seasonal={"ramadan": 2.0}),
        Product("Hummus", "حمص", "Mezze", "pcs", _p(("2025-04-01", 16.0)), 3.5, 40, seasonal={"ramadan": 1.5}),
        Product("Fattoush", "فتوش", "Mezze", "pcs", _p(("2025-04-01", 18.0)), 4.0, 30, seasonal={"ramadan": 2.2, "summer": 1.2}),
        Product("Falafel (6 pcs)", "فلافل 6 حبات", "Mezze", "pcs", _p(("2025-04-01", 12.0)), 2.6, 38, seasonal={"ramadan": 1.7}),
        Product("Lentil Soup", "شوربة عدس", "Soups", "pcs", _p(("2025-04-01", 14.0)), 2.8, 6, seasonal={"ramadan": 6.0, "winter": 2.0, "summer": 0.3}),
        Product("Fresh Lemon Mint", "ليمون بالنعناع", "Drinks", "pcs", _p(("2025-04-01", 16.0)), 3.0, 44, seasonal={"summer": 1.7, "ramadan": 0.8}),
        Product("Jallab", "جلاب", "Drinks", "pcs", _p(("2025-04-01", 15.0)), 3.2, 3, seasonal={"ramadan": 12.0}),
        Product("Soft Drink Can", "مشروب غازي", "Drinks", "pcs", _p(("2025-04-01", 6.0)), 1.8, 70, seasonal={"summer": 1.3}),
        Product("Kunafa", "كنافة", "Desserts", "pcs", _p(("2025-04-01", 22.0)), 7.0, 14, seasonal={"ramadan": 3.0, "eid_fitr": 2.5}),
        Product("Family Meal Box (4 people)", "وجبة عائلية 4 أشخاص", "Family Meals", "pcs", _p(("2025-09-01", 129.0)), 52.0, 6, launched=date(2025, 9, 1), seasonal={"ramadan": 2.5}),
    ],
    competitors=[
        Competitor("Al Mallah Restaurant", "https://almallah.example.ae", {
            "Chicken Shawarma Sandwich": [(10, 13.0)], "Mixed Grill Platter": [(10, 75.0)], "Hummus": [(10, 15.0)],
        }),
        Competitor("Shawarma Station Al Barsha", "https://shawarmastation.example.ae", {
            "Chicken Shawarma Sandwich": [(4, 16.0)], "Beef Shawarma Sandwich": [(4, 20.0)],
        }),
    ],
)

NOUR_BEAUTY = Company(
    key="nour",
    industry_key="salon", city="Riyadh", location=(24.699, 46.6853),
    business_name="Nour Beauty Lounge",
    owner_name="Huda Al-Otaibi",
    email_local="huda",
    country="SA",
    currency="SAR",
    business_type="Beauty salon & spa (services) with retail hair and skin care",
    language="ar",
    target_markets=[{"market_type": "COUNTRY", "country_code": "SA"}],
    receipts_per_day=22, lines_per_receipt=(1, 3), weekend=(4, 5), weekend_factor=1.5, yearly_growth=0.15,
    export_format="csv_ar_cp1256", export_period="quarter", discount_rate=0.1, discount_pcts=(10, 15, 20),
    review_language_mix={"ar": 0.7, "en": 0.3}, reviews_per_month=12,
    documents=["salon_booking_policy", "salon_price_list"],
    products=[
        Product("Women's Haircut & Styling", "قص وتصفيف الشعر", "Hair Services", "service", _p(("2025-04-01", 150.0), ("2026-01-01", 170.0)), None, 5.5, seasonal={"eid_fitr": 2.8, "eid_adha": 2.3}),
        Product("Blow-dry", "سشوار", "Hair Services", "service", _p(("2025-04-01", 90.0)), None, 7, seasonal={"eid_fitr": 3.0, "eid_adha": 2.4}),
        Product("Hair Colour (full)", "صبغة شعر كاملة", "Hair Services", "service", _p(("2025-04-01", 450.0)), None, 1.4, seasonal={"eid_fitr": 2.0}),
        Product("Keratin Treatment", "علاج الكيراتين", "Hair Services", "service", _p(("2025-04-01", 900.0)), None, 0.45, seasonal={"summer": 1.6}),
        Product("Classic Facial", "تنظيف بشرة", "Skin Services", "service", _p(("2025-04-01", 280.0)), None, 2.4, seasonal={"eid_fitr": 1.8}),
        Product("Hydrafacial", "هيدرافيشل", "Skin Services", "service", _p(("2025-08-01", 550.0)), None, 0.9, launched=date(2025, 8, 1)),
        Product("Manicure & Pedicure", "مناكير وباديكير", "Nail Services", "service", _p(("2025-04-01", 180.0)), None, 4.8, seasonal={"eid_fitr": 2.5, "eid_adha": 2.0}),
        Product("Gel Nails", "أظافر جل", "Nail Services", "service", _p(("2025-04-01", 220.0)), None, 3, seasonal={"eid_fitr": 2.2}),
        Product("Bridal Package", "باقة العروس", "Packages", "service", _p(("2025-04-01", 3500.0)), None, 0.12, seasonal={"summer": 2.5, "eid_adha": 1.5}),
        Product("Argan Repair Shampoo 300ml", "شامبو الأرغان 300 مل", "Retail Hair Care", "pcs", _p(("2025-04-01", 95.0)), 41.0, 2.2, stock=48),
        Product("Argan Repair Mask 250ml", "ماسك الأرغان 250 مل", "Retail Hair Care", "pcs", _p(("2025-04-01", 120.0)), 52.0, 1.3, stock=30),
        Product("Vitamin C Serum 30ml", "سيروم فيتامين سي 30 مل", "Retail Skin Care", "pcs", _p(("2025-04-01", 210.0)), 88.0, 0.9, stock=22),
        Product("SPF 50 Sunscreen 50ml", "واقي شمس SPF 50", "Retail Skin Care", "pcs", _p(("2025-04-01", 135.0)), 58.0, 1.4, stock=36, seasonal={"summer": 2.0, "winter": 0.5}),
    ],
    competitors=[
        Competitor("Lamsat Beauty Center", "https://lamsat-beauty.example.sa", {
            "Women's Haircut & Styling": [(9, 160.0)], "Classic Facial": [(9, 300.0)], "Manicure & Pedicure": [(9, 170.0)],
        }),
        Competitor("Glow Spa Riyadh", "https://glowspa.example.sa", {
            "Hydrafacial": [(14, 600.0)], "Keratin Treatment": [(14, 850.0)],
        }),
    ],
)

PETRA_INDUSTRIAL = Company(
    key="petra",
    industry_key="hardware", city="Amman", location=(31.8705, 36.005),
    business_name="Petra Industrial Supplies",
    owner_name="Samer Khoury",
    email_local="samer",
    country="JO",
    currency="JOD",
    business_type="Industrial supplies manufacturer & B2B distributor (steel, pipes, fasteners)",
    language="en",
    target_markets=[{"market_type": "COUNTRY", "country_code": "JO"}, {"market_type": "COUNTRY", "country_code": "IQ"}, {"market_type": "COUNTRY", "country_code": "PS"}],
    receipts_per_day=6, lines_per_receipt=(1, 5), weekend=(4, 5), weekend_factor=0.15, yearly_growth=0.06,
    export_format="xlsx_en_erp", export_period="quarter", discount_rate=0.35, discount_pcts=(3, 5, 7, 10),
    review_language_mix={"en": 0.6, "ar": 0.4}, reviews_per_month=2,
    documents=["b2b_terms", "industrial_catalog"],
    products=[
        Product("Galvanized Steel Pipe 2in (per m)", "ماسورة حديد مجلفن 2 إنش (متر)", "Pipes", "m", _p(("2025-04-01", 6.850), ("2025-11-01", 7.240)), 5.100, 160, stock=4200.0, fractional=True),
        Product("PVC Pipe 110mm (per m)", "ماسورة PVC 110 ملم (متر)", "Pipes", "m", _p(("2025-04-01", 2.375)), 1.480, 230, stock=6500.0, fractional=True, seasonal={"summer": 1.3}),
        Product("Steel Rebar 12mm (per ton)", "حديد تسليح 12 ملم (طن)", "Steel", "ton", _p(("2025-04-01", 512.000), ("2025-10-01", 538.500), ("2026-05-01", 529.000)), 468.000, 2.6, stock=85.0, fractional=True, seasonal={"summer": 1.4, "winter": 0.7}),
        Product("Galvanized Sheet 1.2mm (per kg)", "صاج مجلفن 1.2 ملم (كيلو)", "Steel", "kg", _p(("2025-04-01", 0.965), ("2025-11-01", 1.012)), 0.780, 900, stock=26000.0, fractional=True),
        Product("Hex Bolt M12 (box of 100)", "براغي سداسية M12 (علبة 100)", "Fasteners", "box", _p(("2025-04-01", 14.500)), 8.900, 22, stock=900),
        Product("Anchor Bolt M16 (box of 50)", "براغي تثبيت M16 (علبة 50)", "Fasteners", "box", _p(("2025-04-01", 21.750)), 13.400, 9, stock=420),
        Product("Gate Valve 2in Brass", "محبس بوابة نحاس 2 إنش", "Valves", "pcs", _p(("2025-04-01", 18.400)), 11.200, 14, stock=380),
        Product("Welding Rod E6013 (5kg pack)", "أسلاك لحام E6013 (5 كيلو)", "Welding", "pack", _p(("2025-04-01", 11.250)), 7.050, 18, stock=600),
        Product("Portland Cement 50kg Bag", "إسمنت بورتلاندي كيس 50 كيلو", "Building Materials", "bag", _p(("2025-04-01", 4.150), ("2026-01-15", 4.320)), 3.480, 260, stock=12000, seasonal={"summer": 1.3, "winter": 0.75}),
        Product("Custom Fabrication (per hour)", "تصنيع حسب الطلب (ساعة)", "Services", "hour", _p(("2025-04-01", 35.000)), None, 9, stock=None, fractional=True),
    ],
    competitors=[
        Competitor("Al-Rajhi Steel Trading", "https://alrajhi-steel.example.jo", {
            "Steel Rebar 12mm (per ton)": [(20, 545.000), (3, 522.000)], "Galvanized Sheet 1.2mm (per kg)": [(3, 0.990)],
        }),
        Competitor("Zarqa Pipe Factory", "https://zarqa-pipes.example.jo", {
            "Galvanized Steel Pipe 2in (per m)": [(7, 6.950)], "PVC Pipe 110mm (per m)": [(7, 2.250)],
        }),
    ],
)

BYTEFIX = Company(
    key="bytefix",
    industry_key="electronics", city="Cairo", location=(30.0561, 31.3301),
    business_name="ByteFix Electronics",
    owner_name="Mostafa Adel",
    email_local="mostafa",
    country="EG",
    currency="EGP",
    business_type="Mobile phones, accessories & repair services",
    language="en",
    target_markets=[{"market_type": "COUNTRY", "country_code": "EG"}],
    receipts_per_day=26, lines_per_receipt=(1, 3), weekend=(4, 5), weekend_factor=1.25, yearly_growth=0.1,
    export_format="xlsx_en", export_period="quarter", discount_rate=0.06, discount_pcts=(5, 10),
    review_language_mix={"en": 0.4, "ar": 0.6}, reviews_per_month=9,
    documents=["electronics_warranty"],
    products=[
        Product("Samsung Galaxy A15 128GB", None, "Smartphones", "pcs", _p(("2025-04-01", 8999.0), ("2025-10-01", 9499.0), ("2026-04-01", 9999.0)), 7900.0, 1.4, stock=18, seasonal={"back_to_school": 1.5, "black_friday": 3.0}),
        Product("Xiaomi Redmi Note 13 256GB", None, "Smartphones", "pcs", _p(("2025-04-01", 10499.0), ("2026-02-01", 11499.0)), 9100.0, 1.1, stock=14, seasonal={"black_friday": 3.0}),
        Product("iPhone 15 128GB", None, "Smartphones", "pcs", _p(("2025-04-01", 47999.0), ("2025-09-20", 45999.0)), 42500.0, 0.25, stock=5, seasonal={"black_friday": 2.5}),
        Product("Fast Charger 25W USB-C", None, "Accessories", "pcs", _p(("2025-04-01", 349.0), ("2026-01-01", 399.0)), 180.0, 9, stock=120),
        Product("Tempered Glass Screen Protector", None, "Accessories", "pcs", _p(("2025-04-01", 120.0)), 25.0, 22, stock=400),
        Product("Silicone Phone Case", None, "Accessories", "pcs", _p(("2025-04-01", 180.0)), 45.0, 14, stock=260),
        Product("Wireless Earbuds Pro", None, "Audio", "pcs", _p(("2025-06-01", 1299.0)), 760.0, 2.2, stock=40, launched=date(2025, 6, 1), seasonal={"black_friday": 3.5, "back_to_school": 1.4}),
        Product("Power Bank 20000mAh", None, "Accessories", "pcs", _p(("2025-04-01", 899.0)), 520.0, 3.5, stock=70, seasonal={"summer": 1.4}),
        Product("Screen Replacement (service)", None, "Repairs", "service", _p(("2025-04-01", 1500.0), ("2026-01-01", 1750.0)), None, 3.2),
        Product("Battery Replacement (service)", None, "Repairs", "service", _p(("2025-04-01", 650.0)), None, 2.6),
        Product("Water Damage Diagnostic", None, "Repairs", "service", _p(("2025-04-01", 300.0)), None, 0.9, seasonal={"summer": 1.8}),
    ],
    competitors=[
        Competitor("2B Computer Cairo", "https://2b-cairo.example.eg", {
            "Samsung Galaxy A15 128GB": [(5, 9799.0)], "Fast Charger 25W USB-C": [(5, 379.0)], "Power Bank 20000mAh": [(5, 949.0)],
        }),
        Competitor("Mobile Clinic Nasr City", "https://mobileclinic.example.eg", {
            "Screen Replacement (service)": [(12, 1600.0)], "Battery Replacement (service)": [(12, 600.0)],
        }),
    ],
)

CLARITY = Company(
    key="clarity",
    industry_key="professional_services", city="Paris", location=(48.8698, 2.3075),
    business_name="Clarity Conseil",
    owner_name="Julien Moreau",
    email_local="julien",
    country="FR",
    currency="EUR",
    business_type="Cabinet de conseil en stratégie et transformation digitale (B2B, services)",
    language="fr",
    target_markets=[{"market_type": "COUNTRY", "country_code": "FR"}, {"market_type": "COUNTRY", "country_code": "BE"}, {"market_type": "COUNTRY", "country_code": "MA"}],
    receipts_per_day=1.3, lines_per_receipt=(1, 2), weekend=(5, 6), weekend_factor=0.0, yearly_growth=0.2,
    export_format="csv_fr_semicolon", export_period="quarter", discount_rate=0.1, discount_pcts=(5, 10),
    review_language_mix={"fr": 0.8, "en": 0.2}, reviews_per_month=1,
    documents=["consulting_services"],
    products=[
        Product("Conseil stratégique (heure)", None, "Conseil", "hour", _p(("2025-04-01", 140.0), ("2026-01-01", 155.0)), None, 9.5, fractional=True, seasonal={"summer": 0.45}),
        Product("Atelier de transformation (journée)", None, "Ateliers", "day", _p(("2025-04-01", 1800.0)), None, 0.25, seasonal={"summer": 0.3}),
        Product("Audit des processus", None, "Audits", "forfait", _p(("2025-04-01", 6500.0)), None, 0.04, seasonal={"summer": 0.4}),
        Product("Accompagnement mensuel (forfait)", None, "Abonnements", "mois", _p(("2025-04-01", 2400.0)), None, 0.0),
        Product("Formation équipe (session)", None, "Formations", "session", _p(("2025-09-01", 950.0)), None, 0.12, launched=date(2025, 9, 1)),
    ],
    competitors=[
        Competitor("Nexa Partners Lyon", "https://nexa-partners.example.fr", {"Conseil stratégique (heure)": [(30, 165.0)]}),
    ],
)

COMPANIES = [ZAYTOUNA, ATLAS, BEIT_SHAWARMA, NOUR_BEAUTY, PETRA_INDUSTRIAL, BYTEFIX, CLARITY]
