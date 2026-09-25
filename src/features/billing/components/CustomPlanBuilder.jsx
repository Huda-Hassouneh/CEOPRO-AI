import {
  BarChart3,
  Bell,
  Bot,
  Boxes,
  BrainCircuit,
  Cable,
  CircleDollarSign,
  Database,
  FileSearch,
  FileText,
  Gauge,
  Globe2,
  Image,
  Lightbulb,
  MessageSquare,
  Package,
  PackageSearch,
  Search,
  Sparkles,
  Target,
  TrendingUp,
  Users
} from "lucide-react";
import { CustomPlanQuantityField } from "./CustomPlanQuantityField.jsx";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";

const FEATURE_ICONS = Object.freeze({
  dashboard_analytics: Gauge,
  market_intelligence: BarChart3,
  market_perception: BrainCircuit,
  demand_prediction: TrendingUp,
  inventory_intelligence: PackageSearch,
  product_management: Boxes,
  competitor_management: Search,
  data_integration: Cable,
  business_recommendations: Lightbulb,
  system_alerts: Bell,
  ai_pricing: CircleDollarSign,
  sentiment_analysis: MessageSquare,
  rag_assistant: Bot,
  document_extraction: FileSearch,
  report_generation: FileText,
  marketing_image_generation: Image,
  tracked_competitors: Target,
  tracked_products: Package,
  connected_data_sources: Globe2,
  team_members: Users,
  document_storage_gb: Database
});

const iconFor = (code = "") => FEATURE_ICONS[code.toLowerCase()] ?? Sparkles;

export function CustomPlanBuilder({
  features = [],
  configuration = {},
  onChange
}) {
  const { locale } = useI18n();
  const formatNumber = (value) =>
    new Intl.NumberFormat(locale === "ar" ? "ar-JO" : "en-US").format(value);

  return (
    <div className="ceopro-custom-plan-controls">
      <div className="ceopro-custom-plan-range-grid">
        {features.map((feature) => {
          const Icon = iconFor(feature.code);
          const selected = Boolean(configuration[feature.id]?.selected);
          const value =
            configuration[feature.id]?.limitValue ?? feature.min ?? 0;
          const name =
            locale === "ar" && feature.name_ar ? feature.name_ar : feature.name;
          const description =
            locale === "ar" && feature.description_ar
              ? feature.description_ar
              : feature.description;
          const unit =
            locale === "ar" ? feature.unit_ar || feature.unit : feature.unit;

          return (
            <article
              className={`ceopro-custom-feature-card ${selected ? "is-selected" : ""}`}
              key={feature.id}
            >
              <label className="ceopro-custom-feature-card__toggle">
                <input
                  type="checkbox"
                  checked={selected}
                  aria-label={name}
                  onChange={(event) =>
                    onChange(feature.id, {
                      selected: event.target.checked,
                      limitValue: feature.type === "limit" ? value : null
                    })
                  }
                />

                <span className="ceopro-range-field__icon" aria-hidden="true">
                  <Icon size={19} />
                </span>

                <span>
                  <strong>{name}</strong>
                  {description && <small>{description}</small>}
                </span>
              </label>

              {feature.type === "limit" && selected && (
                <CustomPlanQuantityField
                  label={name}
                  value={value}
                  min={feature.min ?? 0}
                  max={feature.max ?? Math.max(value, 1)}
                  step={feature.step ?? 1}
                  onChange={(nextValue) =>
                    onChange(feature.id, {
                      selected: true,
                      limitValue: nextValue
                    })
                  }
                  formatValue={(nextValue) =>
                    `${formatNumber(nextValue)}${unit ? ` ${unit}` : ""}`
                  }
                />
              )}
            </article>
          );
        })}
      </div>
    </div>
  );
}
