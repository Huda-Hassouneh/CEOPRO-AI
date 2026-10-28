import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronsDown, MessageSquareText, RefreshCw, ShieldCheck, UtensilsCrossed } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { ApexButton, Meter, Panel, Pill, StateBlock } from '../../../shared/components/apex/Apex.jsx';
import {
  completenessTone, facetGaps, facetNextStep, facetsWorthRetrying, facetTone, FACET_ORDER, nextStepKey, onRequestAction, reasonKey, RETRYABLE_FACETS,
  retryFindings, retryOutcome,
} from '../api/competitorDataApi.js';
import { useRetryCompetitor, useRetryFacet } from '../hooks/useCompetitorData.js';

// What happened to a Retry, as a translation key.
export function retryNoticeKey(outcome) {
  return `competitorData.outcome.${outcome}`;
}

export function useRetryNotice(competitorId) {
  const retry = useRetryCompetitor();
  const [notice, setNotice] = useState(null);
  const background = useRetryFacet();
  // The plain Retry always names its facets (the free sources); PRICES and SOCIAL_CONTENT have their own buttons
  // (runOnRequest) because they read a website / a paid provider and run in the background.
  const run = (facets = RETRYABLE_FACETS) => {
    setNotice(null);
    retry.mutate({ id: competitorId, facets }, {
      onSuccess: (data) => setNotice({ kind: retryOutcome(data), findings: retryFindings(data) }),
      onError: (error) => setNotice({ kind: error?.response?.status === 429 ? 'tooSoon' : 'error' }),
    });
  };
  const runOnRequest = (facet, depth = 'standard') => {
    setNotice(null);
    background.mutate({ id: competitorId, facets: [facet], depth }, {
      onSuccess: (data) => setNotice({ kind: retryOutcome(data), facet }),
      onError: (error) => setNotice({ kind: error?.response?.status === 429 ? 'tooSoon' : 'error', facet }),
    });
  };
  return { run, runOnRequest, notice, pending: retry.isPending, backgroundPending: background.isPending, backgroundVariables: background.variables };
}

// Why a facet is empty, in words: the reason, the specific detail the collector recorded (what is actually missing),
// and who can fix it. Shown as text, never only in a tooltip, so it reads on touch screens and with a keyboard.
// The collector's detail often restates the generic reason; show it only when it adds something.
const plain = (text) => String(text).toLowerCase().replace(/[.\s]+$/, '');
function sameSentence(detail, reason) {
  const a = plain(detail);
  const b = plain(reason);
  return a === b || b.startsWith(a) || a.startsWith(b);
}

// Owners cannot set a provider key: say who can, and offer a ready message to send them. The collector's
// detail names the environment variable, so it is not shown to the owner in that case.
function AskOperator({ facet, t }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(t('competitorData.nextStep.requestMessage', { what: t(`competitorData.facet.${facet}`) }));
      setCopied(true);
    } catch { /* clipboard blocked: the sentence above still tells them what to ask */ }
  };
  return <button type="button" className="data-completeness__copy" onClick={copy}>{t(copied ? 'competitorData.nextStep.requestCopied' : 'competitorData.nextStep.askOperator')}</button>;
}

export function FacetReason({ code, detail, nextStep, facet, t }) {
  const reason = t(reasonKey(code));
  const ownerCannotFix = nextStep === 'admin';
  return (
    <>
      <span>{reason}</span>
      {detail && !ownerCannotFix && !sameSentence(detail, reason) && <span className="data-completeness__detail" dir="auto">{detail}</span>}
      {nextStep && nextStep !== 'none' && <span className={`data-completeness__next data-completeness__next--${nextStep}`}>{t(nextStepKey(nextStep))}</span>}
      {ownerCannotFix && facet && <AskOperator facet={facet} t={t} />}
    </>
  );
}

// What a Retry just answered for each facet that did not fully succeed.
export function RetryFindings({ findings, t }) {
  if (!findings?.length) return null;
  return (
    <ul className="data-completeness__findings">
      {findings.map((f) => (
        <li key={f.name}>
          <strong>{t(`competitorData.facet.${f.name}`)}</strong>
          <FacetReason code={f.reasonCode} detail={f.detail} nextStep={f.nextStep} facet={f.name} t={t} />
        </li>
      ))}
    </ul>
  );
}

// One competitor's data, facet by facet: collected, or the reason it is not and what can be done.
export function DataCompleteness({ completeness, competitorId, queued = false }) {
  const { t, locale } = useI18n();
  const navigate = useNavigate();
  const { run, runOnRequest, notice, pending, backgroundPending, backgroundVariables } = useRetryNotice(competitorId);
  const date = useMemo(() => new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }), [locale]);

  const worthRetrying = facetsWorthRetrying(completeness);
  const retryAction = worthRetrying.length === 0 && completeness?.facets ? null : (
    <ApexButton size="sm" variant="secondary" icon={RefreshCw} loading={pending} onClick={() => run(worthRetrying.length ? worthRetrying : undefined)}>
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
          {completeness.needs_setup?.length > 0 && (
            <p className="apex-muted data-completeness__setup">
              {t('competitorData.completeness.needsSetup', { count: completeness.needs_setup.length, parts: completeness.needs_setup.map((name) => t(`competitorData.facet.${name}`)).join(', ') })}
            </p>
          )}
          <ul className="data-completeness">
            {FACET_ORDER.filter((name) => completeness.facets[name]).map((name) => {
              const facet = completeness.facets[name];
              const done = facet.status === 'SUCCEEDED';
              const nextStep = facetNextStep(facet);
              // A per-facet Retry only where trying again can help (not for a missing key, and not for the on-request facets, which have their own buttons).
              const canRetryHere = !done && nextStep === 'retry' && RETRYABLE_FACETS.includes(name);
              return (
                <li key={name} className="data-completeness__row">
                  <div>
                    <strong>{t(`competitorData.facet.${name}`)}</strong>
                    <div className="apex-muted data-completeness__why">
                      {done ? t('competitorData.completeness.items', { count: facet.items_found }) : <FacetReason code={facet.reason_code} detail={facet.reason_detail} nextStep={nextStep} facet={name} t={t} />}
                    </div>
                    <div className="apex-muted data-completeness__when">
                      {facet.last_attempt_at ? t('competitorData.lastTry', { date: date.format(new Date(facet.last_attempt_at)) }) : t('competitorData.never')}
                    </div>
                  </div>
                  <div className="data-completeness__state">
                    <Pill tone={facetTone(facet.status)}>{t(`competitorData.status.${facet.status}`)}</Pill>
                    <FacetRequestButtons
                      name={name}
                      action={onRequestAction(completeness, name)}
                      busy={backgroundPending && backgroundVariables?.facets?.[0] === name}
                      onRun={runOnRequest}
                      t={t}
                    />
                    {canRetryHere && (
                      <ApexButton size="sm" variant="ghost" icon={RefreshCw} loading={pending} onClick={() => run([name])}>{t('competitorData.retryThis')}</ApexButton>
                    )}
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
      <div className="data-completeness__notice" role="status" aria-live="polite">
        <p>{notice ? t(retryNoticeKey(notice.kind)) : ''}</p>
        <RetryFindings findings={notice?.findings} t={t} />
      </div>
    </Panel>
  );
}

// PRICES re-reads the competitor's website and its menu files; "Load more" reads further (more pages, more menu
// files). SOCIAL_CONTENT reads the competitor's own social posts through the paid provider. MARKET_MENUS reads its
// delivery-app listings and menu photos (Google Maps, the web). All start a background job (the result appears here
// shortly), so a click never holds the screen.
export function FacetRequestButtons({ name, action, busy, onRun, t }) {
  if (!action) return null;
  if (name === 'PRICES') {
    return (
      <>
        <ApexButton size="sm" variant="ghost" icon={RefreshCw} loading={busy} onClick={() => onRun('PRICES')}>{t('competitorData.actions.retryPrices')}</ApexButton>
        {action.canLoadMore && (
          <ApexButton size="sm" variant="ghost" icon={ChevronsDown} disabled={busy} title={t('competitorData.actions.loadMoreHint')} onClick={() => onRun('PRICES', 'deep')}>{t('competitorData.actions.loadMore')}</ApexButton>
        )}
      </>
    );
  }
  if (name === 'SOCIAL_CONTENT') {
    return (
      <>
        <ApexButton size="sm" variant="ghost" icon={MessageSquareText} loading={busy} title={t('competitorData.actions.readPostsHint')} onClick={() => onRun('SOCIAL_CONTENT')}>{t('competitorData.actions.readPosts')}</ApexButton>
        {action.canLoadMore && (
          <ApexButton size="sm" variant="ghost" icon={ChevronsDown} disabled={busy} title={t('competitorData.actions.loadMoreHint')} onClick={() => onRun('SOCIAL_CONTENT', 'deep')}>{t('competitorData.actions.loadMore')}</ApexButton>
        )}
      </>
    );
  }
  if (name === 'MARKET_MENUS') {
    return (
      <>
        <ApexButton size="sm" variant="ghost" icon={UtensilsCrossed} loading={busy} title={t('competitorData.actions.readMenusHint')} onClick={() => onRun('MARKET_MENUS')}>{t('competitorData.actions.readMenus')}</ApexButton>
        {action.canLoadMore && (
          <ApexButton size="sm" variant="ghost" icon={ChevronsDown} disabled={busy} title={t('competitorData.actions.loadMoreHint')} onClick={() => onRun('MARKET_MENUS', 'deep')}>{t('competitorData.actions.loadMore')}</ApexButton>
        )}
      </>
    );
  }
  return null;
}

// The same information as one line under a competitor in a list: rating, comments and
// people agreeing, sentiment, how complete the data is, and a Retry when something is missing.
export function CompetitorDataChips({ data, competitorId }) {
  const { t, locale } = useI18n();
  const { run, runOnRequest, notice, pending, backgroundPending } = useRetryNotice(competitorId);
  const number = useMemo(() => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }), [locale]);
  if (!data) return null;
  const completeness = data.data_completeness;
  const gaps = facetGaps(completeness);
  // Retry is offered only where it can help: not when every gap needs the administrator or nothing can be done.
  const worthRetrying = facetsWorthRetrying(completeness);
  const missing = worthRetrying.length > 0;
  // No price collected yet: offer the website / menu read right in the list.
  const pricesMissing = Boolean(onRequestAction(completeness, 'PRICES')) && completeness.facets.PRICES.status !== 'SUCCEEDED';
  return (
    <div className="competitor-data-chips">
      {data.rating != null && <span>{t('competitorData.overview.rating', { rating: number.format(data.rating), count: number.format(data.rating_count || 0) })}</span>}
      {data.comments_collected > 0
        ? <span>{t('competitorData.overview.comments', { count: number.format(data.comments_collected) })}{data.people_agreeing > 0 ? ` · ${t('competitorData.overview.agreeing', { count: number.format(data.people_agreeing) })}` : ''}</span>
        : <span className="apex-muted">{t('competitorData.overview.noComments')}</span>}
      {data.sentiment_label && <Pill tone={data.sentiment_label === 'Positive' ? 'success' : data.sentiment_label === 'Negative' ? 'danger' : 'neutral'}>{t(`competitorData.overview.sentiment.${data.sentiment_label}`)}</Pill>}
      {completeness && <Pill tone={completenessTone(completeness.score)}>{t('competitorData.completeness.score', { score: completeness.score })}</Pill>}
      {missing && <ApexButton size="sm" variant="ghost" icon={RefreshCw} loading={pending} onClick={() => run(worthRetrying)}>{t('competitorData.retry')}</ApexButton>}
      {pricesMissing && <ApexButton size="sm" variant="ghost" icon={RefreshCw} loading={backgroundPending} onClick={() => runOnRequest('PRICES')}>{t('competitorData.actions.retryPrices')}</ApexButton>}
      <span className="apex-muted" role="status" aria-live="polite">{notice ? t(retryNoticeKey(notice.kind)) : ''}</span>
      {gaps.length > 0 && (
        <details className="competitor-data-chips__why">
          <summary>{t('competitorData.whyMissing', { count: gaps.length })}</summary>
          <ul className="data-completeness__findings">
            {gaps.map((g) => (
              <li key={g.name}>
                <strong>{t(`competitorData.facet.${g.name}`)}</strong>
                <FacetReason code={g.reasonCode} detail={g.detail} nextStep={g.nextStep} facet={g.name} t={t} />
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
