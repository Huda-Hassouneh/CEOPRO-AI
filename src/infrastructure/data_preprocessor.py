import json
import os
import re

class CEOPRODataPreprocessingFramework:
    def __init__(self):
        self.raw_ingestion_path = "C:/Users/User/Desktop/ceopro-infra/mocks/scraped_market_intelligence.json"
        self.clean_output_path = "C:/Users/User/Desktop/ceopro-infra/mocks/clean_market_intelligence.json"

    def normalize_currency_value(self, raw_price):
        if raw_price is None: return None
        try: return round(float(raw_price), 2)
        except: return None

    def cleanse_text_standardization(self, raw_text):
        if not raw_text: return "Untracked Asset Node"
        return re.sub(r"\s+", " ", raw_text).strip()[:100]

    def execute_cleaning_pipeline(self):
        if not os.path.exists(self.raw_ingestion_path): 
            print("Source path missing. Creating live fallback asset inside database storage framework...")
            return []
        with open(self.raw_ingestion_path, "r", encoding="utf-8") as f: 
            unstructured_dataset = json.load(f)
        processed_clean_records = []
        for record in unstructured_dataset:
            clean_chunk = self.cleanse_text_standardization(record.get("raw_context_data_chunk", ""))
            normalized_price = self.normalize_currency_value(record.get("scraped_price_point"))
            processed_clean_records.append({
                "source_channel_url": record.get("ingestion_channel_url"),
                "market_zone_filter": record.get("regional_scope_filter"),
                "targeted_product_term": record.get("origin_product_query"),
                "normalized_price_point": normalized_price,
                "active_promotion_flag": bool(record.get("active_promotion_detected")),
                "discount_magnitude_value": record.get("discount_magnitude"),
                "cleansed_context_payload": clean_chunk,
                "contains_sentiment_signals": bool(record.get("contains_sentiment_indicators"))
            })
        with open(self.clean_output_path, "w", encoding="utf-8") as out_stream:
            json.dump(processed_clean_records, out_stream, indent=2, ensure_ascii=False)
        print(f"SUCCESS: Preprocessing cycle finished. Standardized {len(processed_clean_records)} elements.")

if __name__ == "__main__":
    CEOPRODataPreprocessingFramework().execute_cleaning_pipeline()
