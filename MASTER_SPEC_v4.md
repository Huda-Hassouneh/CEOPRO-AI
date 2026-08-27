# CEOPRO AI — Comprehensive Master Technical Specification (Version 4)

> Synced verbatim from `Version_4.txt` (the master spec shared across all teams). Content unchanged; only Markdown headers added at each `====` delimited section for readability/navigation on GitHub.

Version 4:

CEOPRO AI
COMPREHENSIVE MASTER TECHNICAL SPECIFICATION

AI-POWERED MULTI-COUNTRY BUSINESS INTELLIGENCE PLATFORM FOR SMEs

Document Classification: Internal / Engineering
Document Type: Complete Integrated Implementation Specification
Version: 3.0
Date: July 2026


## 0. IMPLEMENTATION DIRECTIVE


This document is the single source of truth for the complete implementation of CEOPRO AI.

The development team must use this document to design and implement one fully integrated, modular, multi-tenant, multi-country AI Business Intelligence Platform for Small and Medium Enterprises.

CEOPRO AI is not an application designed specifically for Jordan.

The platform must be designed from the beginning to support approximately 15 countries, primarily across the Middle East and Africa, with the ability to expand to additional countries in the future without rewriting the core system.

The exact supported country list must be configurable and must not be hardcoded into the business logic.

The system must support different countries through configuration, localization, country-specific adapters, and country-specific data policies.

The objective is not to build a collection of disconnected AI models.

The objective is to build one integrated platform in which:

Business data,
External market data,
Data ingestion,
Data cleaning,
AI models,
Business logic,
Currency handling,
Localization,
Dashboards,
Alerts,
Recommendations,
Chatbot capabilities,
and country-specific configurations

operate as one coherent system.

The developer must not make architectural decisions that contradict this document without explicitly documenting the change and its technical justification.

The system must be:

Modular.
Scalable.
Multi-tenant.
Multi-country.
Multi-currency.
Multilingual.
Explainable.
Privacy-aware.
Open-source-first.
Free of mandatory paid software subscriptions.
Self-hostable.
Able to operate in Arabic and English.
Able to support regional Arabic dialects without requiring the project team to train a language model from scratch.
Able to support future African and Middle Eastern languages.
Designed for heterogeneous SME data sources.
Designed so AI models are replaceable.
Designed so country-specific rules do not contaminate the global core architecture.
Designed so the system remains functional when external data sources are unavailable.
Designed so one country can have different data sources, currencies, regulations, and languages from another country.
Designed for progressive expansion from a single-country deployment to a multi-country regional platform.

The architecture must prioritize practical implementation and system integration over unnecessary technological complexity.


## MULTI-COUNTRY PLATFORM PRINCIPLE


CEOPRO AI must be implemented as one global platform with country-aware configuration.


The platform must NOT be implemented as:

Jordan version
+
Egypt version
+
Saudi Arabia version
+
South Africa version
+
separate independent applications.

Instead, the platform must use:

GLOBAL CORE PLATFORM
+
COUNTRY CONFIGURATION
+
COUNTRY-SPECIFIC ADAPTERS
+
TENANT CONFIGURATION.

The core platform must remain shared.

Country-specific differences must be implemented through configuration and modular adapters.

The system must support:

Country.
Region.
Currency.
Timezone.
Language.
Supported locale.
Number format.
Date format.
Tax configuration.
Business rules.
Legal and data handling policy.
Available data sources.
Supported payment and POS integrations.
Country-specific market data sources.

A tenant must have:

tenant_country
operating_countries
primary_currency
supported_currencies
timezone
preferred_language
supported_languages
business sector
country-specific configuration.

A single tenant may operate in:

One country.
Multiple countries.
Multiple branches across different countries.

The architecture must support all three cases.

## 2. TARGET GEOGRAPHY


The initial target market is approximately 15 countries primarily across:

The Middle East.
North Africa.
Sub-Saharan Africa.
Other African markets where the platform is later deployed.

The exact initial countries must be configurable and must not be embedded as hardcoded assumptions.

The system must not assume:

One currency.
One language.
One tax system.
One legal framework.
One POS provider.
One market data source.
One internet infrastructure.
One date format.
One timezone.
One business culture.
One Arabic dialect.

The system must be designed so that adding a new country primarily requires:

Country configuration.
Currency configuration.
Language configuration.
Country-specific data-source adapters.
Country-specific compliance configuration.
Country-specific tax and business rules where required.

The core application must not require complete rewriting.


## 3. SYSTEM DEFINITION


CEOPRO AI is an AI-powered Business Intelligence platform for Small and Medium Enterprises operating across multiple countries.

The platform receives:

Internal business data.
External market data.
Competitor data.
Publicly available information where technically and legally appropriate.
User-provided documents.
Reviews and market perception data.
Optional country-specific data sources.

The platform transforms raw data into:

Structured business information.
Historical analytics.
Forecasts.
Market intelligence.
Competitor intelligence.
Sentiment analysis.
Pricing insights.
Business recommendations.
Explainable alerts.

The system exposes the results through:

Executive dashboard.
Natural-language RAG chatbot.
Automated alerts.
Explainable recommendations.
Reports.
Historical analysis.
Trend monitoring.

The chatbot must be connected to the actual tenant’s data.

The chatbot must not behave as a generic AI chatbot.

The AI system must distinguish between:

FACT:
Directly retrieved information from the database or verified source.

PREDICTION:
Output generated by a forecasting or machine learning model.

RECOMMENDATION:
Business suggestion generated from data, models, and rules.

ASSUMPTION:
An explicitly identified assumption.

UNKNOWN INFORMATION:
Information that the system does not currently possess.

The system must never present a prediction as a confirmed fact.


## 4. GLOBAL AND COUNTRY-AWARE ARCHITECTURE


The system must use the following logical architecture:

PRESENTATION LAYER
|
v
API GATEWAY AND APPLICATION LAYER
|
+– Authentication
+– Authorization
+– Tenant Management
+– Country Configuration
+– Localization
+– Currency Services
+– Business Logic
+– AI Orchestration
+– Alerting
|
v
DATA INGESTION LAYER
|
+– POS Connectors
+– ERP Connectors
+– CRM Connectors
+– E-commerce Connectors
+– CSV
+– Excel
+– REST APIs
+– Webhooks
+– Scheduled Polling
+– Public APIs
+– RSS / Feeds
+– Public Structured Data
+– Controlled Public Web Collection
|
v
RAW DATA STORAGE
|
+– PostgreSQL
+– MinIO
|
v
DATA PROCESSING LAYER
|
+– Schema Validation
+– Deduplication
+– Normalization
+– Language Detection
+– Country Detection
+– Currency Normalization
+– Missing Value Handling
+– Outlier Detection
+– Entity Resolution
+– Data Quality Scoring
|
v
FEATURE AND KNOWLEDGE LAYER
|
+– PostgreSQL
+– Feature Tables
+– FAISS
+– BM25
+– Document Metadata
|
v
AI SERVICES
|
+– Information Extraction
+– Sentiment Analysis
+– Demand Forecasting
+– Price Intelligence
+– Competitor Ranking
+– Anomaly Detection
+– RAG Retrieval
+– LLM Reasoning
|
v
BUSINESS INTELLIGENCE LAYER
|
+– KPI Calculation
+– Forecast Aggregation
+– Market Perception Index
+– Competitor Scoring
+– Price Recommendations
+– Alerts
+– Explanations
|
v
DELIVERY LAYER
|
+– Dashboard
+– Chatbot
+– Reports
+– Alerts
+– API Responses


## 5. ZERO-MANDATORY-PAID-COST PRINCIPLE


The platform must not require a paid software subscription to operate.
All default software components must be free to use, open-source, or self-hostable under licenses compatible with the intended deployment.

This principle means:

NO MANDATORY PAID SOFTWARE LICENSES.

It does NOT mean:

NO INFRASTRUCTURE COST.

The system must explicitly distinguish between:

Software licensing cost.
Compute cost.
Storage cost.
Bandwidth cost.
Electricity cost.
Hardware cost.
Hosting cost.

The architecture must support a minimum viable single-server deployment.

Initial deployment must be possible using:

Docker Compose.
PostgreSQL.
Redis.
MinIO.
Backend services.
Frontend.
CPU-based inference where practical.

The platform must be designed to operate on:

A single affordable server for development and early deployments.
A larger server or institutional infrastructure.
A dedicated high-performance infrastructure provided by a partner such as Orange.
A multi-node deployment when required.

The exact infrastructure provided by Orange must be verified separately.

The system must not assume that the Orange infrastructure is cloud or on-premise until the actual deployment environment is confirmed.

The architecture must support both possibilities.


## 6. DEFAULT TECHNOLOGY STACK


BACKEND:

Python.
FastAPI.
Pydantic.
SQLAlchemy.
Alembic.

DATABASE:

PostgreSQL.

OBJECT STORAGE:

MinIO.

CACHE AND QUEUE:

Redis.

BACKGROUND PROCESSING:

Celery.

WORKFLOW ORCHESTRATION:

Prefect OSS OR Apache Airflow.

The team must avoid using multiple orchestration tools for the same responsibility without a clear technical reason.

AI:

PyTorch.
Hugging Face Transformers.
XLM-RoBERTa.
XGBoost.
LightGBM where useful.
Sentence Transformers.
FAISS.
BM25 implementation.

MONITORING:

Prometheus.
Grafana.
OpenTelemetry.
Loki or another self-hosted logging system.

MODEL TRACKING:

MLflow.

CONTAINERIZATION:

Docker.
Docker Compose.
K3s/Kubernetes only when actual scale requires it.

FRONTEND:

React.
TypeScript.
Vite.
Open-source component library.

The system must not require:

Paid OpenAI API.
Paid Anthropic API.
Paid vector database.
Paid database plan.
Paid cloud storage.
Paid monitoring service.
Paid workflow service.


## 7. LOCAL LLM AND MULTILINGUAL AI STRATEGY


The platform must use a local open-weight LLM by default where practical.

Possible model families include:

Llama-family models.
Mistral-family models.
Qwen-family models.
Aya-family models.
Other suitable open-weight multilingual models.

The exact model must be selected according to:

Available hardware.
Arabic performance.
English performance.
Other target-language performance.
Arabic dialect understanding.
Code-switching capability.
Model license.
Quantization support.
Inference speed.
Memory requirements.

The project team must NOT train an LLM from scratch.

The project team must NOT be required to create a complete dialect dataset for all countries.

The system must use pretrained multilingual models.

Before final model selection, the development team must create a small evaluation set containing representative examples from:

Modern Standard Arabic.
Jordanian / Levantine Arabic.
Gulf Arabic.
Egyptian Arabic.
North African Arabic where relevant.
English.
Arabic-English code-switching.
Product names.
Prices.
Currency expressions.
Business terminology.

This evaluation set is for model selection and validation.

It is NOT a requirement to train a new language model.

The model must be evaluated for:

Understanding.
Accuracy.
Business reasoning.
Arabic dialect comprehension.
Mixed Arabic-English handling.
Hallucination behavior.

If a local LLM produces unreliable factual explanations, the system must use a safer architecture:

DATABASE FACTS
+
MODEL PREDICTIONS
+
RULE-BASED EXPLANATION TEMPLATES
+
OPTIONAL LLM LANGUAGE POLISHING.

The LLM must not be the source of business facts.


## 8. MULTI-LANGUAGE AND LOCALIZATION


The platform must support:

Arabic.
English.

The architecture must allow future support for:
French.
Swahili.
Amharic.
Hausa.
Other relevant languages.

All user-facing text must support localization.

The system must not hardcode user-facing text inside business logic.

Localization must support:

UI text.
Error messages.
Notifications.
Reports.
Chatbot responses.
Dates.
Numbers.
Currency formatting.

Arabic must support:

Right-to-left interface.
Arabic numerals where configured.
Arabic date formatting.
Mixed Arabic-English text.

English must support:

Left-to-right interface.

The platform must support Arabic-English code-switching.


## 9. MULTI-CURRENCY ARCHITECTURE


Currency must be treated as a first-class platform entity.

Every financial record must store:

Original amount.
Original currency.
Transaction timestamp.
Exchange rate used where conversion occurs.
Converted amount where required.
Conversion source.
Conversion timestamp.

The system must NEVER silently convert money without preserving the original value.

Example:

Original:
100,000 EGP.

Original Currency:
EGP.

Converted:
1,800 JOD.

Conversion Rate:
Recorded.

Conversion Source:
Recorded.

Conversion Timestamp:
Recorded.

The system must support:

JOD.
EGP.
SAR.
AED.
QAR.
KWD.
BHD.
OMR.
MAD.
TND.
DZD.
USD.
EUR.
ZAR.
Other currencies required by supported countries.

The actual supported currency list must be configuration-driven.

Currency conversion must preferably use:

A reliable official or publicly accessible exchange-rate source.
A self-hosted or open solution where possible.
Cached rates with timestamps.

The LLM must NOT be trusted to know current exchange rates from its pretrained knowledge.

If the chatbot needs a current exchange rate, the system must provide a tool or service that retrieves the current rate.

The currency service must support:

Latest exchange rate.
Historical exchange rate.
Currency conversion.
Rate timestamp.
Source tracking.
Fallback behavior.

If exchange-rate data is unavailable, the system must explicitly indicate that conversion cannot be verified.


## 10. MULTI-COUNTRY DATABASE MODEL


Every tenant must have:

tenant_id.
country_code.
operating_countries.
primary_currency.
supported_currencies.
timezone.
preferred_language.
supported_languages.

Every country-specific record must preserve its geographic context.

Relevant entities may include:

country_code.
region_code.
city.
branch.
timezone.
currency.

The database must support:

TENANT
USER
COUNTRY
REGION
BRANCH
PRODUCT
TRANSACTION
INVENTORY
SUPPLIER
COMPETITOR
COMPETITOR_PRODUCT
COMPETITOR_PRICE
REVIEW
NEWS_RECORD
SOCIAL_MENTION
EXTRACTED_ENTITY
SENTIMENT_RESULT
DEMAND_FORECAST
PRICE_RECOMMENDATION
COMPETITOR_SCORE
ALERT
EVIDENCE_RECORD
RECOMMENDATION_OUTCOME
DATA_SOURCE
INGESTION_JOB
MODEL_VERSION
AUDIT_LOG.


## 11. COUNTRY CONFIGURATION LAYER


The system must have a dedicated country configuration layer.

Country configuration may include:

Country code.
Country name.
Default currency.
Supported currencies.
Timezones.
Languages.
Date format.
Number format.
Tax configuration.
Business rules.
Data retention requirements.
Available public data sources.
Supported integrations.
Market data source priority.
Country-specific feature availability.

Country-specific configuration must not require rewriting core AI services.

Example:

COUNTRY CONFIGURATION
|
+– Currency
+– Timezone
+– Language
+– Tax Rules
+– Data Sources
+– Legal Policy
+– Market Sources
+– Business Rules.


## 12. DATA INGESTION SYSTEM


The ingestion system must be connector-based.

Every source must implement a common connector contract.

Supported sources include:

POS.
ERP.
CRM.
E-commerce.
REST API.
GraphQL API.
Webhooks.
CSV.
Excel.
JSON.
XML.
SFTP.
Database exports.
Scheduled files.

The system must not assume that all countries use the same POS system.

The platform must use a canonical internal data model.

Each external source must be mapped into the canonical model.
The system must provide a Universal Import Engine.

The engine must:

Receive a file.
Detect file type.
Inspect columns.
Detect possible schema.
Suggest mappings.
Allow user confirmation.
Validate values.
Detect currency.
Detect date format.
Detect timezone where possible.
Report invalid records.
Import valid records.
Preserve invalid records.
Store original files.
Record import history.

The system must never silently discard invalid data.


## 13. DATA COLLECTION POLICY ENGINE


The Market Data Collection module must include a Collection Policy Engine.

The system must classify every external source as:

ALLOWED
RESTRICTED
BLOCKED.

The system must prefer:

Official public API.
Public RSS/feed.
Public structured data such as schema.org or JSON-LD.
Controlled public web collection where appropriate.

The system must not treat scraping as the default solution.

The policy engine must:

Maintain source status.
Record collection method.
Record collection justification.
Respect applicable technical restrictions.
Respect source terms where applicable.
Respect rate limits.
Disable sources that cannot be safely used.
Log decisions.

Social media must be treated as an optional data source.

The platform must continue functioning if all social media data becomes unavailable.

The system must not depend on social media for:

Demand forecasting.
Competitor ranking.
Sentiment.
Market intelligence.

Social media may improve confidence and coverage, but it must not be a single point of failure.

If social data is unavailable:

The system must degrade in confidence, not fail completely.


## 14. PERSONAL DATA HANDLING


Reviews, social mentions, and customer data may contain personal information.

The system must implement:

Data classification.
Retention policies.
Pseudonymization where possible.
Anonymization where identity is not required.
Tenant-level deletion capability.
Audit logging for deletion.

The system must separate:

RAW PERSONAL DATA
from
DERIVED AGGREGATED INSIGHTS.

Deleting raw personal data must not necessarily destroy historical aggregate metrics.

Example:

The original review text may be deleted.

The historical aggregate sentiment metric may remain if it no longer allows identification of the individual.

Retention policies must be configurable per data category and deployment requirements.

This must be implemented from Phase 1.


## 15. INFORMATION EXTRACTION


The system must support:

Arabic.
English.
Arabic-English mixed content.

The system must use pretrained multilingual models.

Possible primary model:

XLM-RoBERTa Base.

The system must not require training a model from scratch.

NER may use:

Pretrained multilingual transformer.
EntityRuler.
Regex patterns.
Fuzzy matching.
Domain-specific rules.

Target entities include:

ORG
PRODUCT
SKU
MONEY
DATE
TIME
GPE
PERSON
PERCENT
DISCOUNT
INVOICE_ID
ORDER_ID
PHONE
EMAIL
ADDRESS
CURRENCY
TAX
SUPPLIER
COMPETITOR.

The final schema must be configurable.


## 16. SENTIMENT ANALYSIS


The system must support multilingual sentiment analysis.

The system must support:

Arabic.
English.
Mixed content.

The initial strategy must prioritize pretrained multilingual models.

Possible model:

XLM-RoBERTa-based sentiment classifier.

The model must output:

Label.
Probabilities.
Confidence.
Model version.

The continuous sentiment score may be calculated as:

positive_probability

negative_probability.

The system must support:

Product sentiment.
Brand sentiment.
Competitor sentiment.
Service sentiment.
Delivery sentiment.
Price sentiment.

The architecture must support future aspect-based sentiment.

If a country has insufficient review data, the system must display:

LOW SAMPLE SIZE.

The system must not present a statistically weak result as a reliable market conclusion.


## 17. MARKET PERCEPTION INDEX


The MPI must combine:

Sentiment.
Source reliability.
Recency.
Volume.
Entity relevance.

The MPI must support:

Business.
Product.
Category.
Competitor.
Market segment.
Country.
Region.

The system must preserve the underlying contributions.

The dashboard must be able to answer:

“Why did the MPI change?”

The MPI must support cross-country analysis only when the comparison is statistically and economically meaningful.

The system must not blindly compare raw sentiment volume between countries with radically different market sizes.


## 18. DEMAND FORECASTING


Demand forecasting must support:

Product.
Store.
Branch.
Country.
Category.

Forecast horizons:

1 day.
7 days.
14 days.
30 days.

Features may include:

Historical sales.
Price.
Discount.
Promotion.
Inventory.
Competitor prices.
Sentiment.
MPI.
Country.
Region.
Store.
Calendar.
Holiday.
Season.

External data must remain optional.

The model must remain functional if external data is unavailable.

Primary model:

XGBoost.

Possible models:

XGBoost.
LightGBM.

Validation:

Walk-forward validation.

The system must compare against:

Naive forecast.
Seasonal naive.
Moving average.
Previous-period baseline.

The AI model must outperform a reasonable baseline before being considered useful.


## 19. PRICE INTELLIGENCE


The pricing system must be multi-currency and country-aware.

The system must never compare raw prices across currencies without conversion.

Price comparison must consider:

Currency.
Exchange rate.
Country.
Market.
Product equivalence.
Taxes where available.
Shipping cost where relevant.
Availability.
Date of collection.

The system must distinguish between:

LOCAL MARKET COMPARISON

and

CROSS-COUNTRY COMPARISON.

A competitor in another country must not automatically be treated as a direct pricing competitor.

The system must account for:

Currency.
Purchasing power where reliable data exists.
Market differences.
Local taxes.
Import costs.
Shipping.
Availability.

The system must not use a simple currency conversion as the only basis for a cross-country pricing recommendation.

The system must never automatically change prices without explicit authorization.

Pricing must use:

Competitor data.
Demand forecast.
Cost.
Margin.
Inventory.
Historical sales.
Country context.
Currency.
Guardrails.

Learned pricing must remain disabled until enough historical price-change data exists.


## 20. COMPETITOR RANKING


Competitor ranking must be transparent by default.

Features:

Price Competitiveness.
Market Perception.
Market Presence.
Product Breadth.
Digital Presence.
Growth Trend.

The system must support:

Country-level ranking.
City-level ranking.
Regional ranking.
Cross-country ranking only when valid.

The system must not compare businesses from different markets using raw values without normalization.

All features must be normalized.

Weights must be configurable.

The system must explain ranking changes.

A learned ranker may be introduced only after enough historical outcomes exist.


## 21. RAG CHATBOT


The chatbot must be Retrieval-Augmented Generation.

The chatbot must retrieve information from:

PostgreSQL.
BM25.
FAISS.
Documents.
Forecasts.
Competitor data.
Market data.
Evidence records.

The workflow is:

USER QUESTION
|
v
QUERY NORMALIZATION
|
v
INTENT CLASSIFICATION
|
v
LANGUAGE DETECTION
|
v
COUNTRY CONTEXT DETECTION
|
v
ENTITY EXTRACTION
|
v
DATE AND FILTER EXTRACTION
|
v
STRUCTURED DATABASE QUERY
+
BM25
+
FAISS
|
v
RESULT FUSION
|
v
OPTIONAL RERANKING
|
v
CONTEXT ASSEMBLY
|
v
LLM REASONING
|
v
VALIDATION
|
v
FINAL ANSWER.

The chatbot must understand questions in:

Arabic.
English.
Mixed Arabic-English.

The chatbot must understand country context.

For example:

“How did sales perform in Egypt compared to Jordan?”

The system must retrieve the correct country-specific data.

The LLM must not invent missing data.


## 22.SHARED EVIDENCE AND CONFIDENCE SYSTEM


Every important AI output must reference a shared EVIDENCE_RECORD.

EVIDENCE_RECORD:

evidence_id.
category.
source_module.
source_record_ids.
confidence_score.
explanation_text.
model_version.
generated_at.
country_context where applicable.
tenant_id.

Category must be one of:

FACT
PREDICTION
RECOMMENDATION
ASSUMPTION
UNKNOWN.

All dashboard outputs, alerts, chatbot answers, and recommendations must use this shared evidence model.

Confidence must not be implemented independently by every AI module.

The system must have one consistent evidence architecture.


## 23. SHARED COLD-START POLICY


All AI modules must follow one unified cold-start policy.

When data is insufficient:

The system must:

Use a baseline.
Reduce automation.
Display low-confidence status.
Explain the lack of data.
Request additional data where useful.

This applies to:

Demand Forecasting:
Use baseline forecasting.

Price Optimization:
Use rules.

Competitor Ranking:
Use transparent weighted scoring.

Product Matching:
Use rules and fuzzy matching with more manual confirmation.

Sentiment:
Display low sample size.

NER:
Use pretrained models and rules with lower confidence.

Every AI module must expose:

Data sufficiency status.
Minimum data requirement.
Current available data volume.
Confidence status.

The frontend must show a consistent message such as:

“Insight confidence is still building because sufficient historical data is not yet available.”


## 24. RECOMMENDATION FEEDBACK LOOP


Every recommendation must create a RECOMMENDATION_OUTCOME record.

Fields:

recommendation_id.
tenant_id.
country.
action_taken.
action_timestamp.
observed_result.
evaluation_window.

action_taken:

accepted.
modified.
rejected.
ignored.

Observed results may include:

Sales change.
Margin change.
Demand change.
Inventory effect.
Customer response.

This data must later support:

Recommendation evaluation.
Model evaluation.
Future pricing models.
Recommendation improvement.

The system must be able to determine whether recommendations were useful.


## 25. MODEL EVALUATION


Every AI model must have an evaluation protocol.

NER:

Precision.
Recall.
Entity F1.

Sentiment:

Accuracy.
Macro F1.
Confusion Matrix.
Calibration.

Forecasting:

MAE.
RMSE.
MASE.
Pinball Loss where applicable.

Pricing:

Realized demand.
Margin impact.
Recommendation accuracy.
Constraint violation rate.

Retrieval:

Recall@K.
Precision@K.
MRR.
NDCG.

Chatbot:

Groundedness.
Citation correctness.
Answer relevance.
Hallucination rate.


## 26. MODEL REGISTRY AND MLOPS


Use MLflow where practical.

Each model must store:

Model name.
Version.
Dataset version.
Feature version.
Training date.
Metrics.
Hyperparameters.
Code version.
Status.

Statuses:

Development.
Candidate.
Staging.
Production.
Archived.

The platform must not require a large enterprise MLOps infrastructure in the first implementation phase.

Advanced MLOps may be introduced progressively.


## 27. RECOMMENDATION AND EXPLAINABILITY


Every important recommendation must explain:

What is recommended.
Why it is recommended.
What data supports it.
What model produced it.
What uncertainty exists.
What could invalidate it.

The system must not simply say:

“AI recommends this.”

It must say:

“Based on the available evidence, the system recommends this because…”


## 28. INFRASTRUCTURE AND ORANGE COMPUTE ENVIRONMENT


The system must support deployment on:

Local development machines.
Single-server environments.
Institutional servers.
High-performance computing infrastructure.
Cloud or on-premise infrastructure.

The infrastructure provided by Orange must be inspected before final deployment.

The implementation team must determine:

Whether the infrastructure is on-premise or cloud.
Available CPU.
Available GPU.
RAM.
Storage.
Network access.
Internet access.
Data retention policy.
Access duration.
Authentication method.

The architecture must not depend on a GPU unless GPU availability is confirmed.

The system must support CPU-only operation where practical.

If a high-performance server is available, it may be used for:

LLM inference.
Embedding generation.
Model training.
Batch processing.

The rest of the system must remain portable.


## 29. API ARCHITECTURE


The backend must use modular FastAPI APIs.

Major API groups:

/auth
/tenants
/users
/countries
/localization
/currencies
/products
/transactions
/inventory
/imports
/connectors
/competitors
/prices
/reviews
/sentiment
/forecasts
/pricing
/ranking
/alerts
/chat
/documents
/models
/evidence
/recommendations
/admin.

All APIs must implement:

Authentication.
Authorization.
Validation.
Pagination.
Filtering.
Sorting.
Rate limiting.
Audit logging.


## 30. FRONTEND


The frontend must support:

Arabic.
English.
RTL.
LTR.
Multi-country data.
Multi-currency display.

Dashboard modules:

Executive Overview.
Sales.
Revenue.
Demand Forecast.
Inventory.
Competitors.
Price Intelligence.
Sentiment.
Market Perception.
Alerts.
Data Sources.
Chatbot.

The user must be able to filter by:

Country.
Region.
Branch.
Product.
Category.
Time.
Currency.

Every AI output must display:

Recommendation.
Confidence.
Reason.
Supporting evidence.
Timestamp.
Model version where applicable.
Country context where applicable.


## 31. SECURITY


Security requirements:

Password hashing.
HTTPS in production.
Secure secret management.
No hardcoded keys.
Tenant isolation.
Input validation.
SQL injection prevention.
File validation.
Rate limiting.
Audit logs.
Least privilege.

Sensitive business data must not be sent to external AI providers by default.


## 32. OBSERVABILITY AND FAILURE HANDLING


The system must remain partially functional when individual components fail.

If a market source fails:

Internal business data continues.

If sentiment fails:

Forecasting continues.

If vector search fails:

Structured database queries continue.

If LLM fails:

Dashboard and structured insights continue.

If a connector fails:

The system logs and retries.

The system must not silently fail.

Monitor:

API latency.
Error rate.
Queue length.
Job duration.
Database performance.
Model latency.
Model confidence.
Data quality.
Data drift.
Prediction drift.
Source availability.


## 33. DATA RETENTION AND BACKUPS


The system must support:

PostgreSQL backups.
MinIO backups.
Model artifact backups.
Configuration backups.

Backups must be tested through actual restoration procedures.

A backup that has never been restored is not considered verified.

Retention policies must be configurable.


## 34. SCALABILITY


STAGE 1:

Single server.

Docker Compose.

Suitable for:

Development.
Pilot deployment.
Small number of tenants.

STAGE 2:

Multiple services.

Multiple machines or K3s.

STAGE 3:

Large deployment.

Kubernetes.

The platform must not begin with unnecessary distributed complexity.

The system must scale progressively.

Stateless APIs must be horizontally scalable.

Workers must be horizontally scalable.

AI inference must be independently scalable.

PostgreSQL remains the system of record.


## 35. DEVELOPMENT PHASES


PHASE 1 — FOUNDATION

Implement:

Authentication.
Multi-tenancy.
Country configuration.
Localization.
PostgreSQL.
MinIO.
Redis.
Docker.
User management.
Product management.
Transaction ingestion.
Excel import.
CSV import.
Data cleaning.
Currency storage.
Basic dashboard.

PHASE 2 — DEMAND INTELLIGENCE

Implement:

Feature engineering.
Baseline forecasts.
XGBoost forecasting.
Walk-forward validation.
Forecast dashboard.
Forecast explanations.
Cold-start policy.
PHASE 3 — RAG CHATBOT

Implement:

Document ingestion.
Sentence Transformers.
FAISS.
BM25.
Hybrid retrieval.
Structured database retrieval.
Local LLM integration.
Evidence references.
Chat history.
Arabic and English support.

PHASE 4 — MARKET INTELLIGENCE

Implement:

Public market data.
News ingestion.
Reviews.
Competitor data.
Information extraction.
Multilingual NER.
Sentiment analysis.
Market Perception Index.

PHASE 5 — PRICE INTELLIGENCE

Implement:

Competitor price collection.
Product matching.
Currency normalization.
Rule-based recommendations.
Margin guardrails.
Recommendation outcome tracking.

PHASE 6 — COMPETITOR RANKING

Implement:

Feature normalization.
Transparent weighted scoring.
Ranking.
Explainability.
Historical ranking.

PHASE 7 — ADVANCED SYSTEM

Implement progressively:

MLflow.
Model registry.
Evaluation gates.
Drift monitoring.
Active learning.
Advanced ranking.
Learned price optimization.
Cross-encoder reranking.
Advanced anomaly detection.


## 36. TESTING STRATEGY


The development team must implement automated testing.

Testing must include:

Unit Tests.
Integration Tests.
API Tests.
Database Tests.
Tenant Isolation Tests.
Data Pipeline Tests.
AI Model Evaluation.
End-to-End Tests.

The test plan must verify:

A tenant cannot access another tenant’s data.
Currency conversion preserves original values.
Missing data is not silently converted to zero.
Invalid data is not silently discarded.
Failed connectors retry correctly.
Failed AI services do not break the entire platform.
Chatbot answers are grounded.
Recommendations are traceable.
Country configuration works correctly.
Arabic and English interfaces function correctly.
RTL and LTR layouts work correctly.

The project team must implement practical testing proportional to the project scope.

Advanced chaos testing and large-scale infrastructure testing may be introduced progressively and should not block the initial MVP.


## 37. FINAL ENGINEERING PRINCIPLES


Do not build disconnected AI demos.
Build one integrated platform.
PostgreSQL is the source of truth.
MinIO stores large objects.
FAISS and BM25 are retrieval indexes.
Redis is not permanent storage.
The LLM is not the database.
The LLM must not invent business facts.
Pretrained multilingual models must be preferred over training models from scratch.
Arabic dialect evaluation is required, but dialect model training is not mandatory.
The system must support multiple countries from the architectural foundation.
Country-specific differences must be configuration-driven.
Currency must be treated as a first-class entity.
Original financial values must always be preserved.
Currency conversion must be traceable.
Cross-country comparisons must not use raw values blindly.
External data sources must be optional.
Social media must not be a single point of failure.
Public data collection must use a policy-based approach.
Personal data must be handled from Phase 1.
Cold-start handling must be unified.
Evidence and confidence must use one shared schema.
Every recommendation must be traceable.
Recommendation outcomes must be tracked.
Forecasting must be evaluated against baselines.
Pricing recommendations must have hard constraints.
No financial action occurs automatically without authorization.
Tenant isolation is mandatory.
Raw data must be preserved.
Invalid data must remain visible.
The platform must continue functioning when individual services fail.
Paid APIs must never be mandatory.
Infrastructure costs must be acknowledged separately from software licensing costs.
The platform must support CPU-only operation where practical.
The architecture must support deployment on partner-provided infrastructure.
The architecture must scale progressively.
Complexity must be introduced only when justified.
Every model must be versioned.
Every prediction must be traceable.
Every important recommendation must be explainable.
The system must distinguish between FACT, PREDICTION, RECOMMENDATION, ASSUMPTION, and UNKNOWN.
The system must support Arabic-English code-switching.
The system must not assume that all countries have the same data sources.
The system must not assume that all countries have the same legal, economic, linguistic, or technical environment.
The platform must be designed as one regional and international product rather than a collection of country-specific applications.


## FINAL IMPLEMENTATION OBJECTIVE


The final CEOPRO AI system must provide SMEs across approximately 15 countries primarily in the Middle East and Africa with the ability to:

Connect their internal business data.
Import data from heterogeneous POS, ERP, CRM, e-commerce, Excel, CSV, and API sources.
Process and clean business data.
Support multiple countries.
Support multiple currencies.
Support Arabic and English.
Handle Arabic-English code-switching.
Analyze internal business performance.
Forecast demand.
Monitor inventory.
Monitor competitors.
Analyze market sentiment.
Calculate market perception.
Compare prices intelligently.
Generate explainable pricing recommendations.
Track recommendation outcomes.
Generate alerts.
Provide a grounded natural-language AI chatbot.
Explain every important insight.
Operate without mandatory paid software subscriptions.
Run on self-hosted or partner-provided infrastructure.
Continue functioning when external sources become unavailable.
Expand to additional countries without rewriting the core platform.

The platform must be implemented as a single integrated, modular, multi-tenant, multi-country, multilingual, multi-currency, explainable AI Business Intelligence system.

The development team must prioritize a reliable, integrated, maintainable, and demonstrable product over unnecessary architectural complexity.

The final system must be designed for real-world expansion beyond a single country from the beginning.
