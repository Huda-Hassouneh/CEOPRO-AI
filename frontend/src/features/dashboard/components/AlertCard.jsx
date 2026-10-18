import { X } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';
import Badge from '../../../shared/components/ui/Badge.jsx';
import { DashboardIcon } from './DashboardIcon.jsx';

export function AlertCard({ t, onDismiss }) {
  return <section className="dashboard-panel dashboard-alert-card"><div className="dashboard-panel__header"><h2><DashboardIcon name="alert" />{t('dashboard.alert.title')}</h2><Badge variant="error">{t('dashboard.alert.priority')}</Badge></div><strong>{t('dashboard.alert.headline')}</strong><p>{t('dashboard.alert.description')}</p><div className="dashboard-alert-card__actions"><Button size="sm" onClick={() => {}}>{t('dashboard.alert.viewProduct')}</Button><Button size="sm" variant="outline" onClick={onDismiss} leadingIcon={<X size={14} />}>{t('dashboard.alert.dismiss')}</Button></div></section>;
}
