import { ChevronRight } from 'lucide-react';
import { DashboardIcon } from './DashboardIcon.jsx';

export function InsightFeedItem({ item, t }) {
  return <article className={`dashboard-insight-item is-${item.tone}`}><span className="dashboard-insight-item__icon"><DashboardIcon name={item.icon} /></span><div><div className="dashboard-insight-item__meta"><span>{t(item.categoryKey)}</span><small>{t(item.timeKey)}</small></div><strong>{t(item.titleKey)}</strong><p>{t(item.descriptionKey)}</p></div><ChevronRight size={17} aria-hidden="true" /></article>;
}
