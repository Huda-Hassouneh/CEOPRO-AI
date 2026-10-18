import { ArrowRight } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';
import Badge from '../../../shared/components/ui/Badge.jsx';
import { DashboardIcon } from './DashboardIcon.jsx';

export function RecommendationCard({ t }) {
  return <section className="dashboard-panel dashboard-recommendation-card"><div className="dashboard-panel__header"><h2><DashboardIcon name="idea" />{t('dashboard.recommendation.title')}</h2><Badge variant="light-success">{t('dashboard.recommendation.badge')}</Badge></div><strong>{t('dashboard.recommendation.headline')}</strong><p>{t('dashboard.recommendation.description')}</p><Button size="sm" variant="outline" trailingIcon={<ArrowRight size={14} />}>{t('dashboard.recommendation.viewDetails')}</Button></section>;
}
