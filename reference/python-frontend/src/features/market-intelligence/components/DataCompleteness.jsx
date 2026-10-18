import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { RefreshCw, ShieldCheck } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { ApexButton, Meter, Panel, Pill, StateBlock } from '../../../shared/components/apex/Apex.jsx';
import {
  completenessTone, facetTone, FACET_ORDER, reasonKey, retryableFacets, retryOutcome,
} from '../api/competitorDataApi.js';
import { useRetryCompetitor } from '../hooks/useCompetitorData.js';

// What happened to a Retry, as a translation key.
export function retryNoticeKey(outcome) {
  return `competitorData.outcome.${outcome}`;
}

export function useRetryNotice(competitorId) {
  const retry = useRetryCompetitor();
  const [notice, setNotice] = useState(null);
  const run = (facets) => {
    setNotice(null);
    retry.mutate({ id: competitorId, facets }, {
      onSuccess: (data) => setNotice({ kind: retryOutcome(data) }),
      onError: (error) => setNotice({ kind: error?.response?.status === 429 ? 'tooSoon' : 'error' }),
    });
  };
  return { run, notice, pending: retry.isPending };
}

// One competitor's data, facet by facet: collected, or the reason it is not and what can be done.
export function DataCompleteness({ completeness, competitorId, queued = false }) {
  const { t, locale } = useI18n();
  const navigate = useNavigate();
  const { run, notice, pending } = useRetryNotice(competitorId);
  const date = useMemo(() => new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }), [locale]);

  const retryAction = (
    <ApexButton size="sm" variant="secondary" icon={RefreshCw} loading={pending} onClick={() => run(undefined)}>
      {pending ? t('competitorData.retrying') : t('competitorData.retry')}
    </ApexButton>
  );

  return (
    <Panel
      eyebrow={t('competitorData.title')}
      title={t('competitorData.completeness.title')}
      subtitle={t('competitorData.completeness.subtitle')}
      actions={retryAction}
    >
      {!completeness?.facets ? <StateBlock compact title={t('competitorData.completeness.unknown')} /> : (
        <>
          <div className="data-completeness__score">
            <Pill tone={completenessTone(completeness.score)}>{t('competitorData.completeness.score', { score: completeness.score })}</Pill>
            <Meter value={completeness.score} max={100} tone={completenessTone(completeness.score) === 'success' ? 'success' : 'accent'} label={t('competitorData.completeness.title')} />
            {queued && <span className="apex-muted">{t('competitorData.outcome.queued')}</span>}
          </div>
          <ul className="data-completeness">
            {FACET_ORDER.filter((name) => completeness.facets[name]).map((name) => {
              const facet = completeness.facets[name];
              const done = facet.status === 'SUCCEEDED';
              return (
                <li key={name} className="data-completeness__row">
                  <div>
                    <strong>{t(`competitorData.facet.${name}`)}</strong>
                    <div className="apex-muted data-completeness__why" title={facet.reason_detail || undefined}>
                      {done ? t('competitorData.completeness.items', { count: facet.items_found }) : t(reasonKey(facet.reason_code))}
                    </div>
                    <div className="apex-muted data-completeness__when">
                      {facet.last_attempt_at ? t('competitorData.lastTry', { date: date.format(new Date(facet.last_attempt_at)) }) : t('competitorData.never')}
                    </div>
                  </div>
                  <div className="data-completeness__state">
                    <Pill tone={facetTone(facet.status)}>{t(`competitorData.status.${facet.status}`)}</Pill>
                    {facet.action === 'review_source' && (
                      <ApexButton size="sm" variant="ghost" icon={ShieldCheck} onClick={() => navigate(routePaths.marketPendingSources)}>{t('competitorData.reviewTerms')}</ApexButton>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </>
      )}
      <p className="data-completeness__notice" role="status" aria-live="polite">{notice ? t(retryNoticeKey(notice.kind)) : ''}</p>
    </Panel>
  );
}

// The same information as one line under a competitor in a list: rating, comments and
// people agreeing, sentiment, how complete the data is, and a Retry when something is missing.
export function CompetitorDataChips({ data, competitorId }) {
  const { t, locale } = useI18n();
  const { run, notice, pending } = useRetryNotice(competitorId);
  const number = useMemo(() => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }), [locale]);
  if (!data) return null;
  const completeness = data.data_completeness;
  const missing = retryableFacets(completeness).length > 0;
  return (
    <div className="competitor-data-chips">
      {data.rating != null && <span>{t('competitorData.overview.rating', { rating: number.format(data.rating), count: number.format(data.rating_count || 0) })}</span>}
      {data.comments_collected > 0
        ? <span>{t('competitorData.overview.comments', { count: number.format(data.comments_collected) })}{data.people_agreeing > 0 ? ` · ${t('competitorData.overview.agreeing', { count: number.format(data.people_agreeing) })}` : ''}</span>
        : <span className="apex-muted">{t('competitorData.overview.noComments')}</span>}
      {data.sentiment_label && <Pill tone={data.sentiment_label === 'Positive' ? 'success' : data.sentiment_label === 'Negative' ? 'danger' : 'neutral'}>{t(`competitorData.overview.sentiment.${data.sentiment_label}`)}</Pill>}
      {completeness && <Pill tone={completenessTone(completeness.score)}>{t('competitorData.completeness.score', { score: completeness.score })}</Pill>}
      {missing && <ApexButton size="sm" variant="ghost" icon={RefreshCw} loading={pending} onClick={() => run(undefined)}>{t('competitorData.retry')}</ApexButton>}
      <span className="apex-muted" role="status" aria-live="polite">{notice ? t(retryNoticeKey(notice.kind)) : ''}</span>
    </div>
  );
}
