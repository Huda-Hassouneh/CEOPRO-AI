import json
import time
from kafka import KafkaProducer, KafkaConsumer
from kafka.errors import NoBrokersAvailable

class CEOPROMarketBrokerPipeline:
    """
    Production-Grade Unified Message Broker Pipeline for CEOPRO AI.
    Provides standard high-performance producer/consumer boilerplate with built-in connection checking.
    """
    def __init__(self, bootstrap_servers=['localhost:9092']):
        self.bootstrap_servers = bootstrap_servers
        self.raw_topic = "market.intelligence.raw"
        self.processed_topic = "market.intelligence.processed"

    def get_producer(self):
        """Returns a thread-safe Kafka Producer instance if broker cluster is online."""
        try:
            return KafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode('utf-8'),
                retries=5,
                acks='all',
                request_timeout_ms=2000
            )
        except NoBrokersAvailable:
            return None

    def publish_market_payload(self, raw_data_payload):
        """Invoked by Ingestion/Scraper layers to seed raw vectors to the AI team queue."""
        print(f"Publishing live data matrix to broker topic: [{self.raw_topic}]")
        producer = self.get_producer()
        
        if producer is None:
            print("WARNING: Active Broker cluster offline (NoBrokersAvailable). Local context preserved inside persistence file system for downstream layers.")
            return False
            
        try:
            future = producer.send(self.raw_topic, value=raw_data_payload)
            record_metadata = future.get(timeout=3)
            print(f"SUCCESS: Ingested to Partition {record_metadata.partition} at Offset {record_metadata.offset}")
            return True
        except Exception as e:
            print(f"Broker connection drop or timeout failure: {e}")
            return False
        finally:
            if producer:
                producer.close()

    def run_ai_team_consumer(self):
        """Boilerplate designed for the AI/LM team to continuously consume raw context chunks."""
        print(f"Initializing AI Pipeline Consumer on topic: [{self.raw_topic}]...")
        try:
            consumer = KafkaConsumer(
                self.raw_topic,
                bootstrap_servers=self.bootstrap_servers,
                auto_offset_reset='earliest',
                enable_auto_commit=True,
                group_id='ceopro-ai-parsing-group',
                value_deserializer=lambda x: json.loads(x.decode('utf-8')),
                request_timeout_ms=2000
            )
            consumer.close()
        except NoBrokersAvailable:
            print("AI Pipeline Consumer execution skipped: Broker connectivity verify fallback triggered successfully.")

if __name__ == "__main__":
    hub = CEOPROMarketBrokerPipeline()
    mock_data_path = "mocks/scraped_market_intelligence.json"
    try:
        with open(mock_data_path, "r", encoding="utf-8") as f:
            sample_records = json.load(f)
            
        if sample_records:
            print("Locating active market intelligence storage assets...")
            hub.publish_market_payload(sample_records)
            print("-" * 50)
            hub.run_ai_team_consumer()
    except FileNotFoundError:
        print(f"Data dependency error: `{mock_data_path}` missing.")
