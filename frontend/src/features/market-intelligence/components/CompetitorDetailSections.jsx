import {COMPETITOR_AI_ACTIONS_ENABLED} from '../config/competitorCapabilities.js';
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
          style={{ background: "var(--ceopro-primary)" }}
        >
          {detail.name ? detail.name.charAt(0).toUpperCase() : "?"}
        </span>

        <div>
          <div className="competitor-title">
            <h1>{detail.name}</h1>
            {COMPETITOR_AI_ACTIONS_ENABLED && <Badge variant={detail.isTracked ? "light-success" : "neutral"}>
              {t(detail.isTracked ? "competitorManagement.active" : "competitorManagement.inactive")}
            </Badge>}
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
