import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import BusinessPageContainer from '../../../shared/components/layout/BusinessPageContainer.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import { DemandPredictionTabs } from '../components/DemandPredictionTabs.jsx';
import '../styles/DemandPrediction.css';

export function InventoryRecommendationsPage() {
  const { t } = useI18n();
  return <BusinessPageContainer wide className="demand-page"><DemandPredictionTabs t={t}/><EmptyState title={t('demand.inventory.comingSoon')} /></BusinessPageContainer>;
}
