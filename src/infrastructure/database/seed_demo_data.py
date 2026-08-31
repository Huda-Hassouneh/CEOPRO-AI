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

        for name in product_names:
            product_id = _deterministic_uuid("product", tenant_id, name)
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
                INSERT INTO inventory (inventory_id, tenant_id, product_id, stock_quantity, reorder_level)
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
            )
            self._seed_tenant(
                cursor, tenant_b, "CEOPRO Logistics KSA", "SA", "SAR",
                ["Industrial Storage Box", "Heavy Duty Pallet", "Cargo Straps Pack"],
                price_range=(90.0, 300.0), stock_range=(150, 600),
                weekend_days=[3, 4], poisson_lambda=8,
            )

            # RAG demo document + chunk. Three real bugs fixed here alongside the
            # P0 column-name fix (found while already touching this block, not
            # left broken next to it): (a) rag_documents_metadata.file_size_bytes
            # is NOT NULL with no default - never supplied, so this INSERT would
            # fail outright; (b) rag_document_chunks' text column is
            # chunk_text_content, not chunk_text; (c) the embedding was a random
            # 1024-dim vector against a vector(384) column (the real embedding
            # model - src/ai/rag/embeddings.py's default - outputs 384 dimensions,
            # confirmed against the model's own config in the migration that added
            # this column) - would fail on a dimension mismatch, not silently
            # truncate. generate_normalized_vector() returns a plain Python list;
            # psycopg2 has no built-in adapter for pgvector, so it's sent as a
            # bracketed literal cast with ::vector (same approach as
            # src/ai/rag/data_access.py's real ingestion path - no new dependency
            # for a format this simple).
            document_id = _deterministic_uuid("rag_document", tenant_a)
            chunk_text_content = (
                "SME localized economic indicators, exchange fluctuations, and cross-border logistics "
                "contracts payload analysis."
            )
            cursor.execute(
                """
                INSERT INTO rag_documents_metadata
                    (document_id, tenant_id, file_name, storage_bucket_path, file_size_bytes, processed_status)
                VALUES (%s, %s, 'seed_market_notes.txt', %s, %s, 'Processed')
                ON CONFLICT (document_id) DO NOTHING;
                """,
                (
                    document_id, tenant_a, f"{tenant_a}/rag/seed_market_notes.txt",
                    len(chunk_text_content.encode("utf-8")),
                ),
            )
            rag_embedding_dim = 384  # sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2's real output size
            hardened_vector = self.generate_normalized_vector(rag_embedding_dim)
            vector_literal = "[" + ",".join(str(x) for x in hardened_vector) + "]"
            cursor.execute(
                """
                INSERT INTO rag_document_chunks
                    (chunk_id, document_id, tenant_id, chunk_index, chunk_text_content, embedding, embedding_model_version)
                VALUES (%s, %s, %s, 0, %s, %s::vector, 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')
                ON CONFLICT (chunk_id) DO NOTHING;
                """,
                (
                    _deterministic_uuid("rag_chunk", document_id, "0"),
                    document_id,
                    tenant_a,
                    chunk_text_content,
                    vector_literal,
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
