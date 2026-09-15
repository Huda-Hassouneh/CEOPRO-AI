import { ArrowDown, ArrowUp, Eye, Minus, PackagePlus, PackageX } from 'lucide-react';

const icons = { increasing: ArrowUp, decreasing: ArrowDown, stable: Minus, restock: PackagePlus, reduce: PackageX, monitor: Eye };

export function DemandStatusBadge({ value, namespace, t }) {
  const Icon = icons[value] || Minus;
  return <span className={`demand-approved-badge is-${value}`}><Icon size={12} aria-hidden="true" />{t(`${namespace}.${value}`)}</span>;
}
