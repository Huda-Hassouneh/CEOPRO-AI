import math
import os
import sys
import random
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2

# Fixed namespace so every seeded entity gets a deterministic UUID - re-running
# this script is then a safe no-op (ON CONFLICT DO NOTHING) rather than piling
# up a fresh set of demo rows on every run.
_SEED_NAMESPACE = uuid.UUID("00000000-0000-0000-0000-0000000000ee")


def _deterministic_uuid(*parts: str) -> str:
    return str(uuid.uuid5(_SEED_NAMESPACE, "|".join(parts)))


def _poisson(lam: float) -> int:
    """Knuth's algorithm - stdlib-only, no numpy dependency for a seed script."""
    limit = math.exp(-lam)
    k = 0
    p = 1.0
    while True:
        k += 1
        p *= random.random()
        if p <= limit:
            return k - 1


class EnterprisePlatformSeeder:
    def __init__(self):
        self.db_url = os.getenv("DATABASE_URL")
        if not self.db_url:
            raise RuntimeError("DATABASE_URL environment variable is not set.")

    def generate_normalized_vector(self, dimensions: int = 1024) -> list:
        raw_vector = [random.gauss(0, 1) for _ in range(dimensions)]
        magnitude = math.sqrt(sum(x**2 for x in raw_vector))
        return [x / magnitude for x in raw_vector]

    def _seed_tenant(
        self, cursor, tenant_id: str, business_name: str, country_code: str,
        currency: str, product_names: list, price_range: tuple,
        stock_range: tuple, weekend_days: list, poisson_lambda: float,
        competitor_name: str, reviews: list, news_items: list, social_items: list,
    ) -> None:
        cursor.execute("SET app.current_tenant_id = %s;", (tenant_id,))
        cursor.execute(
            """
            INSERT INTO companies (tenant_id, business_name, country_code, primary_currency)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (tenant_id) DO NOTHING;
            """,
            (tenant_id, business_name, country_code, currency),
        )

        user_id = _deterministic_uuid("user", tenant_id)
        cursor.execute(
            """
            INSERT INTO users (user_id, tenant_id, email, password_hash, role)
            VALUES (%s, %s, %s, 'seed_data_placeholder_hash', 'owner')
            ON CONFLICT (user_id) DO NOTHING;
            """,
            (user_id, tenant_id, f"manager.{country_code.lower()}@ceopro.ai"),
        )

        product_ids_by_name = {}
        for name in product_names:
            product_id = _deterministic_uuid("product", tenant_id, name)
            product_ids_by_name[name] = product_id
            base_price = round(random.uniform(*price_range), 2)

            cursor.execute(
                """
                INSERT INTO products (product_id, tenant_id, product_name, current_price, currency, source)
                VALUES (%s, %s, %s, %s, %s, 'MANUAL')
                ON CONFLICT (product_id) DO NOTHING;
                """,
                (product_id, tenant_id, name, base_price, currency),
            )

            cursor.execute(
                """
                INSERT INTO inventory (inventory_id, tenant_id, product_id, current_stock, reorder_level)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (product_id) DO NOTHING;
                """,
                (_deterministic_uuid("inventory", product_id), tenant_id, product_id,
                 random.randint(*stock_range), 20),
            )

            for days_ago in range(30):
                tx_date = datetime.now(timezone.utc) - timedelta(days=days_ago)
                day_weight = 1.4 if tx_date.weekday() in weekend_days else 1.0
                quantity = max(1, int(_poisson(poisson_lambda) * day_weight))
                total_price = round(quantity * base_price, 2)
                cursor.execute(
                    """
                    INSERT INTO transactions
                        (transaction_id, tenant_id, product_id, quantity_sold, unit_price,
                         total_price, original_currency, transaction_date)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                    """,
                    (str(uuid.uuid4()), tenant_id, product_id, quantity, base_price,
                     total_price, currency, tx_date),
                )

            cursor.execute(
                """
                INSERT INTO demand_forecasts
                    (forecast_id, tenant_id, product_id, expected_demand, forecast_target_date, model_version)
                VALUES (%s, %s, %s, %s, (CURRENT_DATE + INTERVAL '7 days'), 'seed-data-baseline')
                """,
                (str(uuid.uuid4()), tenant_id, product_id, random.randint(90, 160)),
            )

        # --- Market Intelligence / Price Intelligence dataset (PENDING_ACTIONS.md #5, #18:
        # competitor_prices and reviews are empty in prod, so pricing/, sentiment/, mpi/, and
        # extraction/ only ever exercise their UNKNOWN/cold-start paths. Seeded here so those
        # modules have real, non-empty input to validate against for once. ---
        competitor_id = _deterministic_uuid("competitor", tenant_id, competitor_name)
        cursor.execute(
            """
            INSERT INTO competitors (competitor_id, tenant_id, competitor_name, country_code, source)
            VALUES (%s, %s, %s, %s, 'MANUAL')
            ON CONFLICT (competitor_id) DO NOTHING;
            """,
            (competitor_id, tenant_id, competitor_name, country_code),
        )

        for name, product_id in product_ids_by_name.items():
            our_price = round(random.uniform(*price_range), 2)
            competitor_price = round(our_price * random.uniform(0.85, 1.15), 2)
            cursor.execute(
                """
                INSERT INTO competitor_prices
                    (price_entry_id, tenant_id, competitor_id, product_name_captured, price_found,
                     currency, is_exact_data, collection_method, source_status)
                VALUES (%s, %s, %s, %s, %s, %s, TRUE, 'MANUAL', 'ALLOWED')
                ON CONFLICT (price_entry_id) DO NOTHING;
                """,
                (_deterministic_uuid("competitor_price", tenant_id, name), tenant_id,
                 competitor_id, name, competitor_price, currency),
            )

        for i, review in enumerate(reviews):
            product_id = product_ids_by_name.get(review.get("product_name"))
            subject_type = "PRODUCT" if product_id else "BUSINESS"
            cursor.execute(
                """
                INSERT INTO reviews
                    (review_id, tenant_id, subject_type, product_id, source_platform, review_text,
                     rating, review_language, review_date, collection_method, source_status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'MANUAL', 'ALLOWED')
                ON CONFLICT (review_id) DO NOTHING;
                """,
                (_deterministic_uuid("review", tenant_id, str(i)), tenant_id, subject_type,
                 product_id, review["platform"], review["text"], review["rating"],
                 review["language"], datetime.now(timezone.utc) - timedelta(days=i * 3)),
            )

        for i, item in enumerate(news_items):
            cursor.execute(
                """
                INSERT INTO news_record (news_id, tenant_id, source_url, headline, body_text, published_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (news_id) DO NOTHING;
                """,
                (_deterministic_uuid("news", tenant_id, str(i)), tenant_id,
                 f"https://example-news.local/{tenant_id}/{i}", item["headline"], item["body_text"],
                 datetime.now(timezone.utc) - timedelta(days=i * 5)),
            )

        for i, item in enumerate(social_items):
            cursor.execute(
                """
                INSERT INTO social_mention (mention_id, tenant_id, platform, mention_text, posted_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (mention_id) DO NOTHING;
                """,
                (_deterministic_uuid("social", tenant_id, str(i)), tenant_id, item["platform"],
                 item["text"], datetime.now(timezone.utc) - timedelta(days=i * 2)),
            )

    def execute_seeding_protocol(self) -> None:
        conn = None
        cursor = None
        try:
            conn = psycopg2.connect(self.db_url)
            conn.autocommit = False
            cursor = conn.cursor()

            tenant_a = _deterministic_uuid("tenant", "ceopro-retail-jordan")
            tenant_b = _deterministic_uuid("tenant", "ceopro-logistics-ksa")
            today = datetime.now(timezone.utc).date()

            for base, target, rate in (("USD", "JOD", 0.7090), ("USD", "SAR", 3.7500), ("JOD", "SAR", 5.2890)):
                cursor.execute(
                    """
                    INSERT INTO currency_rates (base_currency, target_currency, rate, rate_date, source)
                    VALUES (%s, %s, %s, %s, 'seed_data')
                    ON CONFLICT (base_currency, target_currency, rate_date) DO UPDATE SET rate = EXCLUDED.rate;
                    """,
                    (base, target, rate, today),
                )

            self._seed_tenant(
                cursor, tenant_a, "CEOPRO Retail Jordan", "JO", "JOD",
                ["Premium Olive Oil 1L", "Arabica Coffee Beans 1KG", "Medjool Dates 500G"],
                price_range=(8.0, 35.0), stock_range=(80, 250),
                weekend_days=[4, 5], poisson_lambda=3,
                competitor_name="Al-Rayan Gourmet Foods",
                reviews=[
                    {"product_name": "Premium Olive Oil 1L", "platform": "MANUAL",
                     "text": "The olive oil is excellent, rich flavor and great value for 18 JOD.",
                     "rating": 5.0, "language": "en"},
                    {"product_name": "Premium Olive Oil 1L", "platform": "MANUAL",
                     "text": "زيت الزيتون ممتاز جداً وطعمه أصلي، بس السعر غالي شوي.",
                     "rating": 4.0, "language": "ar"},
                    {"product_name": "Arabica Coffee Beans 1KG", "platform": "MANUAL",
                     "text": "القهوة وصلت متأخرة والكيس كان مفتوح، خدمة سيئة.",
                     "rating": 2.0, "language": "ar"},
                    {"product_name": "Medjool Dates 500G", "platform": "MANUAL",
                     "text": "Good dates, nothing special but consistent quality every order.",
                     "rating": 3.5, "language": "en"},
                    {"product_name": None, "platform": "MANUAL",
                     "text": "دعم العملاء متعاون جداً وردوا علي بسرعة، تجربة شراء ممتازة بشكل عام.",
                     "rating": 4.5, "language": "ar"},
                ],
                news_items=[
                    {"headline": "Al-Rayan Gourmet Foods launches 20% off promotion",
                     "body_text": "Al-Rayan Gourmet Foods announced a 20% off promotion on olive oil "
                                  "products this week, pricing Premium Olive Oil around 16.50 JOD, "
                                  "undercutting most local retailers in Amman."},
                ],
                social_items=[
                    {"platform": "twitter",
                     "text": "Just bought Premium Olive Oil 1L for 18 JOD, way better than Al-Rayan Gourmet Foods honestly"},
                ],
            )
            self._seed_tenant(
                cursor, tenant_b, "CEOPRO Logistics KSA", "SA", "SAR",
                ["Industrial Storage Box", "Heavy Duty Pallet", "Cargo Straps Pack"],
                price_range=(90.0, 300.0), stock_range=(150, 600),
                weekend_days=[3, 4], poisson_lambda=8,
                competitor_name="Gulf Pack Solutions",
                reviews=[
                    {"product_name": "Heavy Duty Pallet", "platform": "MANUAL",
                     "text": "Pallets are sturdy and arrived on schedule, exactly as ordered.",
                     "rating": 5.0, "language": "en"},
                    {"product_name": "Heavy Duty Pallet", "platform": "MANUAL",
                     "text": "الطبالي وصلت متكسرة وكان في نقص بالكمية، مو مقبول أبداً.",
                     "rating": 1.0, "language": "ar"},
                    {"product_name": "Cargo Straps Pack", "platform": "MANUAL",
                     "text": "الحزام الأمان جيد للاستخدام اليومي، بس ودي لو كان فيه ألوان أكثر.",
                     "rating": 3.5, "language": "ar"},
                    {"product_name": None, "platform": "MANUAL",
                     "text": "Reliable logistics partner overall, invoicing could be faster though.",
                     "rating": 4.0, "language": "en"},
                ],
                news_items=[
                    {"headline": "Gulf Pack Solutions expands storage box catalog",
                     "body_text": "Gulf Pack Solutions signed a distribution deal covering Industrial "
                                  "Storage Box units at SAR 250 per unit, a 10% discount versus last "
                                  "quarter's list price."},
                ],
                social_items=[
                    {"platform": "twitter",
                     "text": "Ordered Heavy Duty Pallet again this month, Gulf Pack Solutions still can't match the price"},
                ],
            )

            document_id = _deterministic_uuid("rag_document", tenant_a)
            cursor.execute(
                """
                INSERT INTO rag_documents_metadata (document_id, tenant_id, file_name, minio_object_key, processed_status)
                VALUES (%s, %s, 'seed_market_notes.txt', %s, 'Processed')
                ON CONFLICT (document_id) DO NOTHING;
                """,
                (document_id, tenant_a, f"{tenant_a}/rag/seed_market_notes.txt"),
            )
            hardened_vector = self.generate_normalized_vector(1024)
            cursor.execute(
                """
                INSERT INTO rag_document_chunks (chunk_id, document_id, tenant_id, chunk_index, chunk_text, embedding)
                VALUES (%s, %s, %s, 0, %s, %s)
                ON CONFLICT (chunk_id) DO NOTHING;
                """,
                (
                    _deterministic_uuid("rag_chunk", document_id, "0"),
                    document_id,
                    tenant_a,
                    "SME localized economic indicators, exchange fluctuations, and cross-border logistics "
                    "contracts payload analysis.",
                    hardened_vector,
                ),
            )

            conn.commit()
            sys.stdout.write("Demo data seeded successfully for 2 tenants.\n")

        except Exception as e:
            if conn:
                conn.rollback()
            sys.stderr.write(f"Seeding failed: {str(e)}\n")
            sys.exit(1)
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()


if __name__ == "__main__":
    seeder = EnterprisePlatformSeeder()
    seeder.execute_seeding_protocol()
