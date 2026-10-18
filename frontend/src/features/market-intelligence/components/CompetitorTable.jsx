import {COMPETITOR_AI_ACTIONS_ENABLED} from '../config/competitorCapabilities.js';
import Badge from '../../../shared/components/ui/Badge.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import { Building2 } from 'lucide-react';

export function CompetitorTable({ t, locale, filtered, rows, onDetails, canEdit, canReactivate, busy, onTrack }) {
  if (!rows || rows.length === 0) {
    return <EmptyState icon={<Building2 size={26} />} title={t('marketMain.empty.competitorsTitle')} description={t(filtered ? 'directoryUx.noMatchesHint' : 'directoryUx.noCompetitorsHint')} />;
  }

  return (
    <div className="competitor-table-wrap" role="region" aria-label={t("market.competitorsPage.title")} tabIndex={0}>
      <table className="market-table competitor-table">
        <thead>
          <tr>
            <th scope="col">{t("market.competitors.name")}</th>
            <th scope="col">{t("market.controls.industry")}</th>
            {/* Sentiment, Price, and Activity columns removed: Not supported by DB */}
            <th scope="col">{t("market.competitors.updated", "Added Date")}</th>
            <th scope="col">{t("market.competitors.actions")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td>
                <span
                  className="market-entity-logo"
                  style={{ background: "var(--ceopro-primary)" }}
                >
                  {row.name ? row.name.charAt(0).toUpperCase() : "?"}
                </span>
                <button type="button" className="competitor-name-link" onClick={()=>onDetails(row.id)}>{row.name}</button> {COMPETITOR_AI_ACTIONS_ENABLED && <Badge variant={row.isTracked ? "light-success" : "neutral"}>{t(row.isTracked ? "competitorManagement.active" : "competitorManagement.inactive")}</Badge>}
                {row.website && (
                  <small>{row.website.replace(/^https?:\/\//, "")}</small>
                )}
              </td>

              <td>{row.industry || "—"}</td>

              <td>
                {row.addedAt ? new Date(row.addedAt).toLocaleDateString(locale) : "—"}
              </td>

              <td>
                <Button variant="outline" size="sm"
                  className="market-table-action"
                  type="button"
                  onClick={() => onDetails(row.id)}
                >
                  {t("market.competitors.viewDetails")}
                </Button>

                {COMPETITOR_AI_ACTIONS_ENABLED && canEdit && (row.isTracked || canReactivate) && <button type="button" disabled={busy} className="market-table-action" onClick={()=>onTrack(row)}>{t(row.isTracked?'competitorManagement.untrack':'competitorManagement.reactivate')}</button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
