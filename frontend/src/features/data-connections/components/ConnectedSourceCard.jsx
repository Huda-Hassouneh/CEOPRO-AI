import { BarChart3, FileText, Globe2, MoreHorizontal } from "lucide-react";
import Card from "../../../shared/components/ui/Card.jsx";
import { ConnectionStatusBadge } from "./ConnectionStatusBadge.jsx";
import { dataCategoryLabel } from '../utils/connectionPresentation.js';

const icons = { analytics: BarChart3, documents: FileText, website: Globe2 };

export function ConnectedSourceCard({
  source,
  t,
  localize,
  locale = 'en',
  formatDate,
  formatNumber,
  onAction,
  busy = false
}) {
  const Icon = icons[source.type] || FileText;
  return (
    <Card className="connected-source-card">
      <div className="connected-source-card__header">
        <span className="connected-source-card__icon">
          <Icon size={19} aria-hidden="true" />
        </span>
        <ConnectionStatusBadge status={source.status} t={t} />
      </div>
      <div>
        <h3>{localize(source.name)}</h3>
        <p>
          {source.lastUpdatedAt
            ? t("connectData.connected.updated", {
                date: formatDate(source.lastUpdatedAt)
              })
            : t("connectData.connected.neverSynced")}
        </p>
      </div>
      <div className="connected-source-card__meta">
        {source.recordCount != null && (
          <span>
            <small>{t("connectData.connected.records")}</small>
            <strong>{formatNumber(source.recordCount)}</strong>
          </span>
        )}
        <span>
          <small>{t("connectData.connected.categories")}</small>
          <strong>{source.categories.map(value => dataCategoryLabel(value, locale, t)).join(" · ")}</strong>
        </span>
      </div>
      <div className="connected-source-card__actions">
        {source.actions.map((action) => (
          <button
            key={action}
            type="button"
            onClick={() => onAction(action, source)}
            disabled={busy}
            aria-busy={busy}
          >
            {action === "details" && <MoreHorizontal size={14} />}
            {t(`connectData.actions.${action}`)}
          </button>
        ))}
      </div>
    </Card>
  );
}
