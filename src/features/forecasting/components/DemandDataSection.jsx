import { FileDown } from 'lucide-react';
import DataStatusBadge from '../../../shared/components/ui/DataStatusBadge.jsx';

export function DemandDataSection({ title, subtitle, dataStatus, exportLabel, onExport, children, className = '' }) {
  return <section className={`demand-approved-panel ${className}`.trim()}><div className="demand-approved-panel__header"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div><div>{dataStatus && <DataStatusBadge status={dataStatus} />}{onExport && <button type="button" className="demand-approved-export" onClick={onExport}><FileDown size={14} />{exportLabel}</button>}</div></div>{children}</section>;
}
