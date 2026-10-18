import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { UI_TESTING_MODE } from '../../../shared/config/uiTestingMode.js';
import BusinessPageContainer from '../../../shared/components/layout/BusinessPageContainer.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import { DemandPredictionTabs } from '../components/DemandPredictionTabs.jsx';
import { getMockDemandOverview } from '../mocks/demandPredictionMockData.js';
import '../styles/DemandPrediction.css';

/** This feature is not implemented against the backend yet; preview is visual-only. */
export function InventoryRecommendationsPage() {
  const { t, locale } = useI18n();
  if (!UI_TESTING_MODE) return (
    <BusinessPageContainer wide className="demand-page">
      <DemandPredictionTabs t={t}/>
      <EmptyState title={t('demand.inventory.comingSoon')} />
    </BusinessPageContainer>
  );
  const { forecasts } = getMockDemandOverview();
  const number = new Intl.NumberFormat(locale);
  const localize = value => value?.[locale] || value?.en || String(value || '—');
  return (
    <BusinessPageContainer wide className="demand-page">
      <DemandPredictionTabs t={t}/>
      <div className="demand-approved-page">
        <h1>{t('demand.tabs.inventory')}</h1>
        <p>{t('uiTesting.sampleDescription')}</p>
        <div className="market-table-wrap" style={{marginTop: 20}}>
          <table className="market-table">
            <thead><tr>
              <th>{t('demandApproved.table.product')}</th>
              <th>{t('demand.detail.currentStock')}</th>
              <th>{t('demandApproved.table.expectedDemand')}</th>
              <th>{t('demand.detail.suggestedQty')}</th>
              <th>{t('demand.detail.recommendedAction')}</th>
            </tr></thead>
            <tbody>{forecasts.map(row => (
              <tr key={row.id}>
                <td>{localize(row.name)}</td>
                <td>{number.format(row.currentStock)}</td>
                <td>{number.format(row.expectedDemand)}</td>
                <td>{number.format(row.suggestedQuantity)}</td>
                <td>{t(`demand.actions.${row.recommendedAction}`)}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </div>
    </BusinessPageContainer>
  );
}
