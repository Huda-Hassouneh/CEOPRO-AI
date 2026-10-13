import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Newspaper, Sparkles } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { ApexButton, Panel, Pill, StateBlock } from '../../../shared/components/apex/Apex.jsx';
import { discoveryApi } from '../api/discoveryApi.js';
import { analysisErrorKey, Citations } from './Citations.jsx';

// Market news found by discovery (industry and competitor headlines, each
// linking to the article) and an AI summary of the trends in it, every
// point citing the articles and competitor facts it rests on.
export function MarketInsights() {
  const { t, locale } = useI18n();
  const queryClient = useQueryClient();
  const date = useMemo(() => new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }), [locale]);
  const news = useQuery({ queryKey: ['discovery-news'], queryFn: () => discoveryApi.news({ limit: 12 }) });
  const summary = useQuery({ queryKey: ['market-analysis'], queryFn: discoveryApi.marketAnalysis });
  const refresh = useMutation({
    mutationFn: discoveryApi.refreshMarketAnalysis,
    onSuccess: (data) => queryClient.setQueryData(['market-analysis'], data),
  });
  const analysis = summary.data && !summary.data.insufficient_evidence ? summary.data : null;
  const errorKey = refresh.isError ? analysisErrorKey(refresh.error) : null;

  return (
    <div className="apex-grid apex-grid--2">
      <Panel
        eyebrow={t('intel.marketEyebrow')}
        title={t('intel.trendsTitle')}
        subtitle={analysis?.generated_at ? t('intel.analysisAt', { date: date.format(new Date(analysis.generated_at)) }) : t('intel.trendsHint')}
        actions={<ApexButton size="sm" icon={Sparkles} loading={refresh.isPending} disabled={!news.data?.length} onClick={() => refresh.mutate()}>{analysis ? t('intel.reanalyse') : t('intel.summarise')}</ApexButton>}
      >
        <p className="intel-ai-label"><Sparkles size={12} aria-hidden="true" /> {t('intel.aiLabel')}</p>
        {errorKey && <p className="market-scan__note is-error" role="alert">{t(`intel.analysisErrors.${errorKey}`)}{errorKey === 'planLimit' && <> <Link to={routePaths.billing}>{t('marketingApex.errors.openBilling')}</Link></>}</p>}
        {summary.data?.insufficient_evidence && <p className="market-scan__note is-warning">{t('intel.insufficient')}</p>}
        {analysis?.language && !refresh.isPending && analysis.language !== (locale?.startsWith('ar') ? 'ar' : 'en') && (
          <p className="market-scan__note">{t('intel.otherLanguage')}</p>
        )}
        {analysis ? (
          <div className="intel-analysis">
            {analysis.trends?.length > 0 && <div><h3>{t('intel.trends')}</h3><ul>{analysis.trends.map((p) => <li key={p.text} dir="auto">{p.text} <Citations citations={p.citations} t={t} /></li>)}</ul></div>}
            {analysis.watch?.length > 0 && <div><h3>{t('intel.watch')}</h3><ul>{analysis.watch.map((p) => <li key={p.text} dir="auto">{p.text} <Citations citations={p.citations} t={t} /></li>)}</ul></div>}
            {!analysis.trends?.length && !analysis.watch?.length && <StateBlock compact title={t('intel.noTrends')} />}
          </div>
        ) : <StateBlock compact title={news.data?.length ? t('intel.noAnalysis') : t('intel.noNewsYet')} description={news.data?.length ? t('intel.trendsHint') : t('intel.noNewsHint')} />}
      </Panel>
      <Panel eyebrow={t('intel.newsEyebrow')} title={t('intel.marketNews')} subtitle={t('intel.newsSource')}>
        {news.isPending ? <StateBlock kind="loading" compact title={t('common.loading')} /> : news.data?.length ? (
          <ul className="intel-news">
            {news.data.map((a) => (
              <li key={a.url}><Newspaper size={14} aria-hidden="true" />
                <div>
                  <a href={a.url} target="_blank" rel="noreferrer noopener" dir="auto">{a.title}</a>
                  <div className="apex-muted">
                    {[a.source_domain, a.published_at && date.format(new Date(a.published_at))].filter(Boolean).join(' · ')}
                    {a.competitor_name && <> · <Pill>{a.competitor_name}</Pill></>}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        ) : <StateBlock compact title={t('intel.noNewsYet')} description={t('intel.noNewsHint')} />}
      </Panel>
    </div>
  );
}

export default MarketInsights;
