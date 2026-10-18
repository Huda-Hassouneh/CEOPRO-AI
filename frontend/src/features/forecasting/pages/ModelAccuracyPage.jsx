import { useMemo, useState } from 'react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import BusinessPageContainer from '../../../shared/components/layout/BusinessPageContainer.jsx';
import PageHeader from '../../../shared/components/layout/PageHeader.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import { getApiErrorMessage } from '../../../shared/lib/apiErrors.js';
import { useModelAccuracy } from '../hooks/useModelAccuracy.js';
import { DemandPredictionTabs } from '../components/DemandPredictionTabs.jsx';
import { forecastFormatters, localize } from '../utils/forecastFormatters.js';
import '../styles/DemandPrediction.css';
export function ModelAccuracyPage() {
  const { t, locale, dir } = useI18n();
  const [periodDays, setPeriodDays] = useState(30);
  const query = useModelAccuracy(periodDays);
  const f = useMemo(() => forecastFormatters(locale), [locale]);
  if (query.isPending) return <Skeleton height='300px' variant='rectangular' />;
  if (query.isError) return <EmptyState title={t('demandApproved.error.title')}
    description={getApiErrorMessage(query.error,t)} action={<Button onClick={()=>query.refetch()}>{t('demandApproved.actions.retry')}</Button>} />;
  const models = query.data?.models ?? [];
  return <BusinessPageContainer wide className='demand-approved-page' dir={dir}>
    <PageHeader title={t('demandApproved.evaluation.title')} subtitle={t('demandApproved.evaluation.description')}
      actions={<select className='demand-approved-select' value={periodDays} aria-label={t('demandApproved.filters.period')} onChange={event=>setPeriodDays(Number(event.target.value))}>
        {[7,30].map(days=><option key={days} value={days}>{t(`demandApproved.filters.last${days}`)}</option>)}
      </select>} />
    <DemandPredictionTabs t={t} inventoryAllowed={query.data?.featureAccess?.inventoryIntelligence === true} />
    <p className='forecast-coverage-note'>{t('demandApproved.evaluation.lowerIsBetter')}</p>
    {models.length ? <div className='demand-table-wrap'><table className='demand-table'>
      <thead><tr>{['product','model','version','trainedAt','mae','rmse','mase','folds'].map(key=><th key={key}>{t(`demandApproved.evaluation.${key}`)}</th>)}</tr></thead>
      <tbody>{models.map(row=><tr key={`${row.productId}:${row.modelVersionId}`}>
        <td>{localize(row.productName,locale)}</td><td>{row.modelName}</td><td>{row.version}</td><td>{f.formatDate(row.trainedAt)}</td>
        <td>{f.formatNumber(row.mae)}</td><td>{f.formatNumber(row.rmse)}</td><td>{f.formatNumber(row.mase)}</td><td>{f.formatNumber(row.nFolds)}</td>
      </tr>)}</tbody>
    </table></div> : <EmptyState title={t('demandApproved.empty.accuracyTitle')} description={t('demandApproved.empty.accuracyDescription')} />}
  </BusinessPageContainer>;
}
