import { ArrowRight } from 'lucide-react';
import Card from '../../../shared/components/ui/Card.jsx';
import { DashboardIcon } from './DashboardIcon.jsx';

export function QuickActionCard({ action, t, onClick }) {
  return <Card className="dashboard-quick-action" interactive onClick={onClick} role="button" tabIndex={0} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onClick?.(); } }}><span className="dashboard-quick-action__icon"><DashboardIcon name={action.icon} /></span><span><strong>{t(action.labelKey)}</strong><small>{t(action.descriptionKey)}</small></span><ArrowRight size={16} aria-hidden="true" /></Card>;
}
