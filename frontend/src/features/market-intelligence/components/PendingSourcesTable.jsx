import Badge from '../../../shared/components/ui/Badge.jsx';
import { safeHref } from '../../../shared/lib/safeUrl.js';

const STATUS_VARIANT = { ALLOWED: 'light-success', RESTRICTED: 'warning', BLOCKED: 'error' };

// One real discovered data_source per row - source_url/competitor_name/
// mapped_product_count/policy_status are all real, unfabricated columns
// data_access.list_tenant_sources() returns, never placeholder values.
export function PendingSourcesTable({ t, rows, onReview }) {
  return <div className="competitor-table-wrap">
    <table className="market-table pending-sources-table">
      <thead>
        <tr>
          <th>{t('market.sources.table.competitor')}</th>
          <th>{t('market.sources.table.url')}</th>
          <th>{t('market.sources.table.status')}</th>
          <th>{t('market.sources.table.products')}</th>
          <th>{t('market.sources.table.discovered')}</th>
          <th>{t('market.sources.table.actions')}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => <tr key={row.source_id}>
          <td><strong>{row.competitor_name || row.source_name}</strong></td>
          <td><a href={safeHref(row.source_url)} target="_blank" rel="noreferrer noopener">{row.source_url}</a></td>
          <td><Badge variant={STATUS_VARIANT[row.policy_status] || 'neutral'}>{t(`market.sources.status.${row.policy_status}`)}</Badge></td>
          <td>{row.mapped_product_count}</td>
          <td>{row.created_at ? new Date(row.created_at).toLocaleDateString(document.documentElement.lang || undefined, { dateStyle: 'medium' }) : '-'}</td>
          <td>
            {row.policy_status === 'RESTRICTED'
              ? <button className="market-table-action" type="button" onClick={() => onReview(row)}>{t('market.sources.table.review')}</button>
              : <span className="pending-sources-table__final">{t(`market.sources.finalized.${row.policy_status}`)}</span>}
          </td>
        </tr>)}
      </tbody>
    </table>
  </div>;
}
