import { useMemo, useState } from 'react';
import { Check, ExternalLink, Eye, MessageSquareText, RefreshCw, ThumbsUp } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { ApexButton, Panel, Pill, StateBlock } from '../../../shared/components/apex/Apex.jsx';
import { facetNextStep } from '../api/competitorDataApi.js';
import { useCommentAction, useCompetitorComments, useCompetitorDataStatus } from '../hooks/useCompetitorData.js';
import { FacetReason, RetryFindings, retryNoticeKey, useRetryNotice } from './DataCompleteness.jsx';

// Only web links are opened from stored data (the server stores nothing else, this keeps it that way).
const safeHref = (url) => (/^https?:\/\//i.test(url || '') ? url : null);
const SORTS = ['helpful', 'recent'];
const ACTIONS = [{ status: 'noted', icon: Eye }, { status: 'acted_on', icon: Check }];
const SENTIMENT_FILTERS = ['negative', 'positive', 'neutral'];
const TONE = { positive: 'success', negative: 'danger', neutral: 'neutral' };
// A well-backed comment is a prompt to act: unhappy customers are an opening, praised strengths are the bar to meet.
const SIGNAL_TONE = { opportunity: 'warning', threat: 'accent' };

function Comment({ comment, t, number, date, onAction, busy, reply = false }) {
  return (
    <li className={`competitor-comment${reply ? ' is-reply' : ''}`}>
      <div className="competitor-comment__head">
        <strong dir="auto">{comment.author || t('competitorData.comments.anonymous')}</strong>
        {comment.rating != null && <span className="apex-num" aria-label={`${comment.rating} / 5`}>★ {number.format(comment.rating)}</span>}
        {safeHref(comment.url) && <a className="competitor-comment__source" href={safeHref(comment.url)} target="_blank" rel="noreferrer noopener" dir="ltr">{t('competitorData.comments.openSource')}<ExternalLink size={11} aria-hidden="true" /></a>}
        {comment.sentiment && <Pill tone={TONE[comment.sentiment] || 'neutral'}>{t(`competitorData.comments.sentiment.${comment.sentiment}`)}</Pill>}
        {comment.signal && <Pill tone={SIGNAL_TONE[comment.signal] || 'neutral'}>{t(`competitorData.comments.signal.${comment.signal}`)}</Pill>}
        <span className="apex-muted">{[comment.platform, comment.date ? date.format(new Date(comment.date)) : null].filter(Boolean).join(' · ')}</span>
      </div>
      <p dir="auto">{comment.text}</p>
      {comment.signal && <p className="competitor-comment__action apex-muted">{t(`competitorData.comments.signalHint.${comment.signal}`)}</p>}
      {!reply && onAction && (
        <div className="competitor-comment__actions" role="group" aria-label={t('competitorData.comments.action.label')}>
          {ACTIONS.map(({ status, icon: Icon }) => (
            <button key={status} type="button" className="apex-btn apex-btn--ghost apex-btn--sm" aria-pressed={comment.action_status === status} disabled={busy}
              onClick={() => onAction(comment.id, comment.action_status === status ? null : status)}>
              <Icon size={13} aria-hidden="true" />{t(`competitorData.comments.action.${status}`)}
            </button>
          ))}
        </div>
      )}
      <div className="competitor-comment__foot apex-muted">
        {comment.people_agreeing > 0 && <span><ThumbsUp size={12} aria-hidden="true" /> {t('competitorData.comments.agree', { count: number.format(comment.people_agreeing) })}</span>}
        {!reply && comment.reply_count > 0 && <span><MessageSquareText size={12} aria-hidden="true" /> {t('competitorData.comments.replies', { count: number.format(comment.reply_count) })}</span>}
      </div>
      {comment.replies?.length > 0 && (
        <ul className="competitor-comment__replies" aria-label={t('competitorData.comments.repliesTo')}>
          {comment.replies.map((r) => <Comment key={r.id} comment={r} t={t} number={number} date={date} reply />)}
        </ul>
      )}
    </li>
  );
}

// Nothing collected: say why (the COMMENTS reason the collector recorded), who can fix it, and offer a Retry only when it can help.
function NoComments({ competitorId, t }) {
  const status = useCompetitorDataStatus(competitorId);
  const { run, notice, pending } = useRetryNotice(competitorId);
  const facet = status.data?.facets?.COMMENTS;
  const nextStep = facetNextStep(facet);
  return (
    <StateBlock
      compact
      title={t('competitorData.comments.empty')}
      description={facet && facet.status !== 'SUCCEEDED' ? undefined : t('competitorData.comments.emptyHint')}
      action={(
        <div className="competitor-comments__why">
          {facet && facet.status !== 'SUCCEEDED' && (
            <p className="data-completeness__why apex-muted"><FacetReason code={facet.reason_code} detail={facet.reason_detail} nextStep={nextStep} facet="COMMENTS" t={t} /></p>
          )}
          {nextStep === 'retry' && (
            <ApexButton size="sm" variant="secondary" icon={RefreshCw} loading={pending} onClick={() => run(['COMMENTS'])}>{t('competitorData.comments.collectNow')}</ApexButton>
          )}
          <div role="status" aria-live="polite">
            {notice && <p className="apex-muted">{t(retryNoticeKey(notice.kind))}</p>}
            <RetryFindings findings={notice?.findings} t={t} />
          </div>
        </div>
      )}
    />
  );
}

// The real comments and reviews collected about a competitor, most agreed-with first.
export function CompetitorComments({ competitorId }) {
  const { t, locale } = useI18n();
  const [sort, setSort] = useState('helpful');
  const [filters, setFilters] = useState({});
  const { sentiment, platform, theme, action } = filters;
  // Choosing a chip that is already chosen clears it.
  const toggle = (key, value) => setFilters((current) => ({ ...current, [key]: current[key] === value ? null : value }));
  const filtered = Boolean(sentiment || platform || theme || action);
  const query = useCompetitorComments(competitorId, sort, filters);
  const mark = useCommentAction(competitorId);
  const number = useMemo(() => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }), [locale]);
  const date = useMemo(() => new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }), [locale]);
  const pages = (query.data?.pages || []).filter(Boolean);
  const summary = pages[0]?.summary;
  const comments = pages.flatMap((page) => page.comments);
  const counts = summary?.sentiment;

  return (
    <Panel
      eyebrow={t('competitorData.title')}
      title={t('competitorData.comments.title')}
      subtitle={t('competitorData.comments.subtitle')}
      actions={(
        <div className="apex-segmented" role="group" aria-label={t('competitorData.comments.sort')}>
          {SORTS.map((key) => <button key={key} type="button" aria-pressed={sort === key} onClick={() => setSort(key)}>{t(`competitorData.comments.${key}`)}</button>)}
        </div>
      )}
    >
      {query.isPending ? <StateBlock kind="loading" compact title={t('common.loading')} />
        : query.isError ? <StateBlock kind="error" compact title={t('competitorData.comments.error')} onRetry={() => query.refetch()} retryLabel={t('demandApex.actions.retry')} />
          : comments.length === 0 && !filtered ? <NoComments competitorId={competitorId} t={t} />
            : (
              <>
                {summary && (
                  <p className="competitor-comments__summary apex-muted">
                    {t('competitorData.comments.summary', { comments: number.format(summary.comments), replies: number.format(summary.replies), agreeing: number.format(summary.people_agreeing) })}
                    {summary.held_back_for_safety > 0 && ` · ${t('competitorData.comments.heldBack', { count: number.format(summary.held_back_for_safety) })}`}
                    {summary.last_collected_at && ` · ${t('competitorData.comments.collected', { date: date.format(new Date(summary.last_collected_at)) })}`}
                  </p>
                )}
                {summary?.themes?.length > 0 && (
                  <div className="competitor-comments__themes">
                    <span className="apex-muted">{t('competitorData.comments.themes')}</span>
                    {summary.themes.map((item) => (
                      <button key={item.theme} type="button" className="competitor-comments__theme" aria-pressed={theme === item.theme} onClick={() => toggle('theme', item.theme)}
                        title={item.example?.text}>
                        {t(`competitorData.comments.theme.${item.theme}`)} · {number.format(item.mentions)}
                        {item.negative > 0 && <span className="competitor-comments__theme-neg"> ({t('competitorData.comments.themeNegative', { count: number.format(item.negative) })})</span>}
                      </button>
                    ))}
                  </div>
                )}
                {counts && (
                  <div className="apex-segmented competitor-comments__filter" role="group" aria-label={t('competitorData.comments.filter')}>
                    <button type="button" aria-pressed={!filtered} onClick={() => setFilters({})}>{t('competitorData.comments.all')}</button>
                    {SENTIMENT_FILTERS.map((key) => (
                      <button key={key} type="button" aria-pressed={sentiment === key} disabled={!counts[key] && sentiment !== key} onClick={() => toggle('sentiment', key)}>
                        {t(`competitorData.comments.sentiment.${key}`)} · {number.format(counts[key] || 0)}
                      </button>
                    ))}
                    <button type="button" aria-pressed={action === 'open'} onClick={() => toggle('action', 'open')}>{t('competitorData.comments.toReview')}</button>
                    {Object.keys(summary.platforms || {}).length > 1 && Object.keys(summary.platforms).map((name) => (
                      <button key={name} type="button" aria-pressed={platform === name} onClick={() => toggle('platform', name)}>{name} · {number.format(summary.platforms[name])}</button>
                    ))}
                  </div>
                )}
                {counts?.not_analysed > 0 && <p className="apex-muted competitor-comments__summary">{t('competitorData.comments.notAnalysed', { count: number.format(counts.not_analysed) })}</p>}
                {mark.isError && <p className="competitor-comments__error" role="alert">{t('competitorData.comments.action.error')}</p>}
                {comments.length === 0 && <p className="apex-muted">{t('competitorData.comments.noneOfKind')}</p>}
                <ul className="competitor-comments">
                  {comments.map((comment) => <Comment key={comment.id} comment={comment} t={t} number={number} date={date} busy={mark.isPending} onAction={(reviewId, status) => mark.mutate({ reviewId, status })} />)}
                </ul>
                {query.hasNextPage && (
                  <div className="competitor-directory__more">
                    <ApexButton size="sm" variant="secondary" loading={query.isFetchingNextPage} onClick={() => query.fetchNextPage()}>{t('competitorData.comments.loadMore')}</ApexButton>
                  </div>
                )}
              </>
            )}
    </Panel>
  );
}

export default CompetitorComments;
