import {
  ArrowRight,
  BarChart3,
  Database,
  MessageCircle,
  Search,
  Tags,
  TrendingUp
} from "lucide-react";
import {
  SectionHeading,
  useLanding
} from "../components/LandingPrimitives.jsx";
import { MiniVisual } from "../components/MarketingVisuals.jsx";

const features = [
  { key: "market", id: "market", Icon: BarChart3 },
  { key: "demand", id: "demand", Icon: TrendingUp },
  { key: "pricing", id: "pricing-intelligence", Icon: Tags },
  { key: "sentiment", id: "sentiment", Icon: MessageCircle },
  { key: "rag", id: "rag", Icon: Search },
  { key: "data", id: "data", Icon: Database }
];

export function FeaturesSection() {
  const { t } = useLanding();
  return (
    <section id="features" className="lp-section">
      <div className="lp-container">
        <SectionHeading section="features" centered />
        <div className="lp-bento">
          {features.map(({ key, id, Icon }) => (
            <a
              className={`lp-feature lp-feature--${key}`}
              href={`#${id}`}
              key={key}
            >
              <span className="lp-icon">
                <Icon size={22} aria-hidden="true" />
              </span>
              <h3>{t(`features.${key}Title`)}</h3>
              <p>{t(`features.${key}Text`)}</p>
              <MiniVisual type={key} />
              <span className="lp-feature-link">
                {t("common.learn")}
                <ArrowRight className="lp-arrow" size={16} aria-hidden="true" />
              </span>
            </a>
          ))}
        </div>
        <p className="lp-demo-caption">{t("common.demo")}</p>
      </div>
    </section>
  );
}
