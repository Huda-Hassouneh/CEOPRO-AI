import { useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import Card from '../../../shared/components/ui/Card.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import { productsApi } from '../../products/api/productsApi.js';
import { competitorsApi } from '../api/competitorsApi.js';
import { mpiApi } from '../api/mpiApi.js';

const SCOPE = { BUSINESS: 'BUSINESS', PRODUCT: 'PRODUCT', COMPETITOR: 'COMPETITOR' };

export function MarketPerceptionPanel({ t }) {
  const [scope, setScope] = useState(SCOPE.BUSINESS);
  const [subjectId, setSubjectId] = useState('');
  const products = useQuery({ queryKey: ['mpi-products'], queryFn: () => productsApi.list({ limit: 100, offset: 0 }) });
  const competitors = useQuery({ queryKey: ['mpi-competitors'], queryFn: competitorsApi.list });
  const summary = useQuery({
    queryKey: ['mpi-summary', scope, subjectId],
    queryFn: () => mpiApi.summary({ subjectType: scope, subjectId: scope === SCOPE.BUSINESS ? undefined : subjectId }),
    enabled: false,
    retry: false,
  });

  useEffect(() => setSubjectId(''), [scope]);
  const options = scope === SCOPE.PRODUCT
    ? (products.data?.products || []).map((item) => ({ id: item.product_id, name: item.product_name }))
    : (competitors.data?.competitors || []).map((item) => ({ id: item.id, name: item.name }));
  const canRequest = scope === SCOPE.BUSINESS || Boolean(subjectId);
  const result = summary.data;
  const lowSample = result?.sample_size?.status === 'LOW_SAMPLE_SIZE';
  const errorStatus = summary.error?.response?.status;

  return <Card className="mpi-panel">
    <header><div><h2>{t('marketPerception.title')}</h2><p>{t('marketPerception.description')}</p></div>
      <Button size="sm" variant="outline" leadingIcon={<RefreshCw size={15} />} disabled={!canRequest || summary.isFetching} loading={summary.isFetching} onClick={() => summary.refetch()}>
        {summary.isFetching ? t('marketPerception.loading') : t('marketPerception.refresh')}
      </Button>
    </header>
    <div className="mpi-controls">
      <label>{t('marketPerception.scope')}<select value={scope} onChange={(event) => setScope(event.target.value)}>
        <option value={SCOPE.BUSINESS}>{t('marketPerception.business')}</option>
        <option value={SCOPE.PRODUCT}>{t('marketPerception.product')}</option>
        <option value={SCOPE.COMPETITOR}>{t('marketPerception.competitor')}</option>
      </select></label>
      {scope !== SCOPE.BUSINESS && <label>{scope === SCOPE.PRODUCT ? t('marketPerception.chooseProduct') : t('marketPerception.chooseCompetitor')}
        <select value={subjectId} onChange={(event) => setSubjectId(event.target.value)}>
          <option value="">{t('marketPerception.choose')}</option>
          {options.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </label>}
    </div>
    {(products.isError || competitors.isError) && scope !== SCOPE.BUSINESS && <p role="alert">{t('marketPerception.subjectLoadError')}</p>}
    {summary.isError && <p role="alert">{errorStatus === 403 ? t('marketPerception.denied') : errorStatus === 404 ? t('marketPerception.subjectMissing') : t('marketPerception.error')}</p>}
    {result && <div className="mpi-result" aria-live="polite">
      {result.status === 'UNKNOWN'
        ? <p>{t('marketPerception.noReviews')}</p>
        : lowSample
          ? <p>{t('marketPerception.insufficient', { count: result.sample_size?.analyzed_count ?? result.review_count ?? 0, minimum: result.sample_size?.minimum_required ?? 0 })}</p>
          : <strong>{t('marketPerception.index')}: {result.mpi} / 100</strong>}
      {result.sample_size && <p>{t('marketPerception.reviewCount', { count: result.sample_size.analyzed_count })}</p>}
      {result.label_counts && <p>{t('marketPerception.breakdown', { positive: result.label_counts.positive ?? 0, neutral: result.label_counts.neutral ?? 0, negative: result.label_counts.negative ?? 0 })}</p>}
      <small>{lowSample ? t('marketPerception.lowSampleNotice') : t('marketPerception.evidenceNotice')}</small>
    </div>}
  </Card>;
}
