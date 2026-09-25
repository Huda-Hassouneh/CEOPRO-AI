import {
  AggregationType,
  FeatureType,
  ResetCycle
} from "../../generated/prisma/enums.js";

export const LEGACY_FEATURE_CODE_MAPPINGS: Readonly<Record<string, string>> =
  Object.freeze({
    ai_queries: "rag_assistant",
    pricing_intelligence: "ai_pricing"
  });

export const CANONICAL_FEATURES = Object.freeze([
  {
    code: "dashboard_analytics",
    name: "Dashboard Analytics",
    name_ar: "تحليلات لوحة التحكم",
    description: "Access to business dashboard analytics, KPIs, charts, and insights.",
    description_ar: "الوصول إلى تحليلات لوحة التحكم ومؤشرات الأداء والرسوم البيانية والرؤى.",
    type: FeatureType.boolean,
    aggregationType: AggregationType.sum,
    resetCycle: ResetCycle.lifetime
  },
  {
    code: "market_intelligence",
    name: "Market Intelligence",
    name_ar: "ذكاء السوق",
    description: "Access to market intelligence, trends, opportunities, and competitive insights.",
    description_ar: "الوصول إلى ذكاء السوق والاتجاهات والفرص والتحليلات التنافسية.",
    type: FeatureType.boolean,
    aggregationType: AggregationType.sum,
    resetCycle: ResetCycle.lifetime
  },
  {
    code: "market_perception",
    name: "Market Perception Index",
    name_ar: "مؤشر تصور السوق",
    description: "Access to Market Perception Index analysis and summaries.",
    description_ar: "الوصول إلى تحليل وملخصات مؤشر تصور السوق.",
    type: FeatureType.boolean,
    aggregationType: AggregationType.sum,
    resetCycle: ResetCycle.lifetime
  },
  {
    code: "demand_prediction",
    name: "Demand Prediction",
    name_ar: "التنبؤ بالطلب",
    description: "Access to demand forecasts, product forecasts, model accuracy, and forecast analysis.",
    description_ar: "الوصول إلى توقعات الطلب وتوقعات المنتجات وتحليل دقة نماذج التنبؤ.",
    type: FeatureType.boolean,
    aggregationType: AggregationType.sum,
    resetCycle: ResetCycle.lifetime
  },
  {
    code: "inventory_intelligence",
    name: "Inventory Intelligence",
    name_ar: "ذكاء المخزون",
    description: "Access to AI-powered inventory recommendations and inventory intelligence.",
    description_ar: "الوصول إلى توصيات المخزون المدعومة بالذكاء الاصطناعي وتحليلات المخزون.",
    type: FeatureType.boolean,
    aggregationType: AggregationType.sum,
    resetCycle: ResetCycle.lifetime
  },
  {
    code: "product_management",
    name: "Product Management",
    name_ar: "إدارة المنتجات",
    description: "Access to product management, inventory, product details, and price history.",
    description_ar: "الوصول إلى إدارة المنتجات والمخزون وتفاصيل المنتجات وسجل الأسعار.",
    type: FeatureType.boolean,
    aggregationType: AggregationType.sum,
    resetCycle: ResetCycle.lifetime
  },
  {
    code: "competitor_management",
    name: "Competitor Management",
    name_ar: "إدارة المنافسين",
    description: "Access to competitor profiles, monitoring, and competitor management.",
    description_ar: "الوصول إلى ملفات المنافسين ومتابعتهم وإدارة المنافسين.",
    type: FeatureType.boolean,
    aggregationType: AggregationType.sum,
    resetCycle: ResetCycle.lifetime
  },
  {
    code: "data_integration",
    name: "Data Integrations",
    name_ar: "تكامل البيانات",
    description: "Access to external data connections and integration capabilities.",
    description_ar: "الوصول إلى مصادر البيانات الخارجية وميزات التكامل.",
    type: FeatureType.boolean,
    aggregationType: AggregationType.sum,
    resetCycle: ResetCycle.lifetime
  },
  {
    code: "business_recommendations",
    name: "Business Recommendations",
    name_ar: "توصيات الأعمال",
    description: "Access to AI-generated business recommendations and actionable insights.",
    description_ar: "الوصول إلى توصيات الأعمال والرؤى القابلة للتنفيذ المدعومة بالذكاء الاصطناعي.",
    type: FeatureType.boolean,
    aggregationType: AggregationType.sum,
    resetCycle: ResetCycle.lifetime
  },
  {
    code: "system_alerts",
    name: "Smart Alerts",
    name_ar: "التنبيهات الذكية",
    description: "Access to realtime business alerts and actionable notifications.",
    description_ar: "الوصول إلى تنبيهات الأعمال الفورية والإشعارات القابلة للتنفيذ.",
    type: FeatureType.boolean,
    aggregationType: AggregationType.sum,
    resetCycle: ResetCycle.lifetime
  },
  {
    code: "ai_pricing",
    name: "AI Pricing Recommendations",
    name_ar: "توصيات التسعير بالذكاء الاصطناعي",
    description: "Number of AI-powered pricing recommendations available per billing period.",
    description_ar: "عدد توصيات التسعير المدعومة بالذكاء الاصطناعي المتاحة خلال دورة الفوترة.",
    type: FeatureType.limit,
    unit: "recommendations",
    unit_ar: "توصية",
    aggregationType: AggregationType.sum,
    resetCycle: ResetCycle.billing_period
  },
  {
    code: "sentiment_analysis",
    name: "Sentiment Analysis",
    name_ar: "تحليل المشاعر",
    description: "Number of records that can be processed by sentiment analysis per billing period.",
    description_ar: "عدد السجلات التي يمكن تحليل مشاعرها خلال دورة الفوترة.",
    type: FeatureType.limit,
    unit: "records",
    unit_ar: "سجل",
    aggregationType: AggregationType.sum,
    resetCycle: ResetCycle.billing_period
  },
  {
    code: "rag_assistant",
    name: "AI Knowledge Assistant",
    name_ar: "مساعد المعرفة بالذكاء الاصطناعي",
    description: "Number of AI knowledge assistant queries available per billing period.",
    description_ar: "عدد الاستفسارات المتاحة لمساعد المعرفة بالذكاء الاصطناعي خلال دورة الفوترة.",
    type: FeatureType.limit,
    unit: "queries",
    unit_ar: "استفسار",
    aggregationType: AggregationType.sum,
    resetCycle: ResetCycle.billing_period
  },
  {
    code: "document_extraction",
    name: "Document Extraction",
    name_ar: "استخراج بيانات المستندات",
    description: "Number of documents that can be processed and extracted per billing period.",
    description_ar: "عدد المستندات التي يمكن معالجتها واستخراج بياناتها خلال دورة الفوترة.",
    type: FeatureType.limit,
    unit: "documents",
    unit_ar: "مستند",
    aggregationType: AggregationType.sum,
    resetCycle: ResetCycle.billing_period
  },
  {
    code: "report_generation",
    name: "AI Report Generation",
    name_ar: "إنشاء التقارير",
    description: "Number of reports that can be generated per billing period.",
    description_ar: "عدد التقارير التي يمكن إنشاؤها خلال دورة الفوترة.",
    type: FeatureType.limit,
    unit: "reports",
    unit_ar: "تقرير",
    aggregationType: AggregationType.sum,
    resetCycle: ResetCycle.billing_period
  },
  {
    code: "marketing_image_generation",
    name: "Marketing Image Generation",
    name_ar: "إنشاء الصور التسويقية",
    description: "Number of AI-generated marketing images available per billing period.",
    description_ar: "عدد الصور التسويقية التي يمكن إنشاؤها بالذكاء الاصطناعي خلال دورة الفوترة.",
    type: FeatureType.limit,
    unit: "images",
    unit_ar: "صورة",
    aggregationType: AggregationType.sum,
    resetCycle: ResetCycle.billing_period
  },
  {
    code: "tracked_competitors",
    name: "Tracked Competitors",
    name_ar: "المنافسون المتابعون",
    description: "Maximum number of competitors that the company can track.",
    description_ar: "الحد الأقصى لعدد المنافسين الذين يمكن للشركة متابعتهم.",
    type: FeatureType.limit,
    unit: "competitors",
    unit_ar: "منافس",
    aggregationType: AggregationType.max,
    resetCycle: ResetCycle.lifetime
  },
  {
    code: "tracked_products",
    name: "Tracked Products",
    name_ar: "المنتجات المتابعة",
    description: "Maximum number of products that the company can manage or track.",
    description_ar: "الحد الأقصى لعدد المنتجات التي يمكن للشركة إدارتها أو متابعتها.",
    type: FeatureType.limit,
    unit: "products",
    unit_ar: "منتج",
    aggregationType: AggregationType.max,
    resetCycle: ResetCycle.lifetime
  },
  {
    code: "connected_data_sources",
    name: "Connected Data Sources",
    name_ar: "مصادر البيانات المتصلة",
    description: "Maximum number of data sources and integrations that can be connected.",
    description_ar: "الحد الأقصى لعدد مصادر البيانات والتكاملات التي يمكن ربطها.",
    type: FeatureType.limit,
    unit: "sources",
    unit_ar: "مصدر",
    aggregationType: AggregationType.max,
    resetCycle: ResetCycle.lifetime
  },
  {
    code: "team_members",
    name: "Team Members",
    name_ar: "أعضاء الفريق",
    description: "Maximum number of users that can belong to the tenant.",
    description_ar: "الحد الأقصى لعدد المستخدمين الذين يمكن إضافتهم إلى الشركة.",
    type: FeatureType.limit,
    unit: "members",
    unit_ar: "عضو",
    aggregationType: AggregationType.max,
    resetCycle: ResetCycle.lifetime
  },
  {
    code: "document_storage_gb",
    name: "Document Storage",
    name_ar: "تخزين المستندات",
    description: "Maximum document and knowledge-base storage available to the tenant.",
    description_ar: "الحد الأقصى لمساحة تخزين المستندات وقاعدة المعرفة المتاحة للشركة.",
    type: FeatureType.limit,
    unit: "GB",
    unit_ar: "جيجابايت",
    aggregationType: AggregationType.max,
    resetCycle: ResetCycle.lifetime
  }
]);

export const CANONICAL_FEATURE_CODES = Object.freeze(
  CANONICAL_FEATURES.map((feature) => feature.code)
);

export function canonicalizeFeatureCode(code: string): string {
  return LEGACY_FEATURE_CODE_MAPPINGS[code] ?? code;
}
