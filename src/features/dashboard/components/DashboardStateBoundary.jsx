import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';

export function DashboardStateBoundary({ status = 'ready', children, title = 'Dashboard', onRetry }) {
  const { t } = useI18n();
  if (status === 'loading') return <div className="dashboard-state-shell" aria-label={title} aria-busy="true"><div className="dashboard-state-grid">{Array.from({ length: 7 }, (_, index) => <Skeleton key={index} height="128px" variant="rectangular" />)}</div><Skeleton height="320px" variant="rectangular" /></div>;
  if (status === 'empty') return <EmptyState title={t('dashboard.executive.emptyTitle')} description={t('dashboard.executive.emptyDescription')} />;
  if (status === 'error') return <div className="dashboard-state-error" role="alert"><strong>{t('dashboard.executive.errorTitle')}</strong><span>{t('dashboard.executive.error')}</span>{onRetry && <Button size="sm" variant="outline" onClick={() => onRetry()}>{t('dashboard.controls.retry')}</Button>}</div>;
  return children;
}
