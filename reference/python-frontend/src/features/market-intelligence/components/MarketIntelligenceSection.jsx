import { FileDown } from 'lucide-react';
import DataStatusBadge from '../../../shared/components/ui/DataStatusBadge.jsx';

export function MarketIntelligenceSection({ title, subtitle, dataStatus, exportLabel, onExport, children, className = '' }) {
  return <section className={`market-main-panel ${className}`.trim()}>
    <div className="market-main-panel__header">
      <div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>
      <div className="market-main-panel__actions">{dataStatus && <DataStatusBadge status={dataStatus} />}{onExport && <button type="button" className="market-main-export" onClick={onExport}><FileDown size={14} aria-hidden="true" />{exportLabel}</button>}</div>
    </div>
    {children}
  </section>;
}
