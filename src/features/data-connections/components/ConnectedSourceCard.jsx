import { BarChart3, FileText, Globe2, MoreHorizontal } from 'lucide-react';
import Card from '../../../shared/components/ui/Card.jsx';
import DataStatusBadge from '../../../shared/components/ui/DataStatusBadge.jsx';
import { ConnectionStatusBadge } from './ConnectionStatusBadge.jsx';

const icons = { analytics: BarChart3, documents: FileText, website: Globe2 };

export function ConnectedSourceCard({ source, t, localize, formatDate, formatNumber, onAction }) {
  const Icon = icons[source.type] || FileText;
  return <Card className="connected-source-card">
    <div className="connected-source-card__header"><span className="connected-source-card__icon"><Icon size={19} aria-hidden="true" /></span><ConnectionStatusBadge status={source.status} t={t} /></div>
    <div><h3>{localize(source.name)}</h3><p>{t('connectData.connected.updated', { date: formatDate(source.lastUpdatedAt) })}</p></div>
    <div className="connected-source-card__meta">
      {source.recordCount != null && <span><small>{t('connectData.connected.records')}</small><strong>{formatNumber(source.recordCount)}</strong>{source.dataStatus && <DataStatusBadge status={source.dataStatus} />}</span>}
      <span><small>{t('connectData.connected.categories')}</small><strong>{source.categories.map(localize).join(' · ')}</strong></span>
    </div>
    <div className="connected-source-card__actions">{source.actions.map((action) => <button key={action} type="button" onClick={() => onAction(action, source)}>{action === 'details' && <MoreHorizontal size={14} />}{t(`connectData.actions.${action}`)}</button>)}</div>
  </Card>;
}
