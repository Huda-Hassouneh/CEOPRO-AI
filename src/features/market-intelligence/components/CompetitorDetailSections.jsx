import {
  ArrowRight,
  CheckCircle2,
  CircleMinus,
  ExternalLink
} from "lucide-react";
import Button from "../../../shared/components/ui/Button.jsx";
import Badge from "../../../shared/components/ui/Badge.jsx";
import { MarketTrendChart } from "./MarketTrendChart.jsx";

export function CompetitorDetailHeader({ t, detail, onBack }) {
  if (!detail) return null;

  return (
    <div className="competitor-detail-header">
      <button type="button" className="market-back-link" onClick={onBack}>
        ← {t("market.detail.back", "Back")}
      </button>

      <div className="competitor-identity">
        <span
          className="competitor-logo"
          style={{ background: "var(--primary-color, #4f46e5)" }}
        >
          {detail.name ? detail.name.charAt(0).toUpperCase() : "?"}
        </span>

        <div>
          <div className="competitor-title">
            <h1>{detail.name}</h1>
            <Badge variant="light-success">
              {t("market.detail.tracked", "Tracked")}
            </Badge>
          </div>

          <p>
            {detail.website && detail.website.replace(/^https?:\/\//, "")}
            {detail.website && detail.addedAt && " · "}
            {detail.addedAt &&
              `${t("market.competitors.updated", "Added")}: ${new Date(detail.addedAt).toLocaleDateString()}`}
          </p>

          {detail.industry && <span>{detail.industry}</span>}
        </div>
      </div>

      <Button variant="outline" size="sm">
        {t("market.detail.monitor", "Monitor")}
      </Button>
    </div>
  );
}

// ----------------------------------------------------------------------
// THE FOLLOWING COMPONENTS ARE UNSUPPORTED BY YOUR SCHEMA
// They return `null` to prevent crashes if they are still imported.
// ----------------------------------------------------------------------

export function StrengthsWeaknesses() {
  return null;
}

export function CompetitorSummary() {
  return null;
}

export function PriceComparison() {
  return null;
}

export function StrategicMoves() {
  return null;
}
