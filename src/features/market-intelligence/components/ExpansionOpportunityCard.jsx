import { Sparkles } from "lucide-react";
import Card from "../../../shared/components/ui/Card.jsx";
import DataStatusBadge from "../../../shared/components/ui/DataStatusBadge.jsx";

export function ExpansionOpportunityCard({ opportunity, t, localize, number }) {
  return (
    <Card className="market-main-opportunity">
      <div className="market-main-opportunity__header">
        <span>
          <Sparkles size={17} />
        </span>
        <DataStatusBadge status={opportunity.dataStatus} />
      </div>
      <h3>{localize(opportunity.productName)}</h3>
      <div className="market-main-opportunity__score">
        <strong>+{number(opportunity.growthPercent)}%</strong>
        <span>{t("marketMain.opportunities.growth")}</span>
      </div>
      <p>{localize(opportunity.explanation)}</p>
    </Card>
  );
}
