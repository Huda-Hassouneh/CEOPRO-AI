import { useMemo, useState } from 'react';
import { MessageSquareText, ThumbsUp } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { ApexButton, Panel, Pill, StateBlock } from '../../../shared/components/apex/Apex.jsx';
import { useCompetitorComments } from '../hooks/useCompetitorData.js';

const SORTS = ['helpful', 'recent'];
const TONE = { positive: 'success', negative: 'danger', neutral: 'neutral' };

function Comment({ comment, t, number, date, reply = false }) {
  return (
    <li className={`competitor-comment${reply ? ' is-reply' : ''}`}>
      <div className="competitor-comment__head">
        <strong dir="auto">{comment.author || t('competitorData.comments.anonymous')}</strong>
        {comment.rating != null && <span className="apex-num" aria-label={`${comment.rating} / 5`}>★ {number.format(comment.rating)}</span>}
        {comment.sentiment && <Pill tone={TONE[comment.sentiment] || 'neutral'}>{t(`competitorData.comments.sentiment.${comment.sentiment}`)}</Pill>}
        <span className="apex-muted">{[comment.platform, comment.date ? date.format(new Date(comment.date)) : null].filter(Boolean).join(' · ')}</span>
      </div>
      <p dir="auto">{comment.text}</p>
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

// The real comments and reviews collected about a competitor, most agreed-with first.
export function CompetitorComments({ competitorId }) {
  const { t, locale } = useI18n();
  const [sort, setSort] = useState('helpful');
  const query = useCompetitorComments(competitorId, sort);
  const number = useMemo(() => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }), [locale]);
  const date = useMemo(() => new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }), [locale]);
  const pages = (query.data?.pages || []).filter(Boolean);
  const summary = pages[0]?.summary;
  const comments = pages.flatMap((page) => page.comments);

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
          : comments.length === 0 ? <StateBlock compact title={t('competitorData.comments.empty')} description={t('competitorData.comments.emptyHint')} />
            : (
              <>
                {summary && (
                  <p className="competitor-comments__summary apex-muted">
                    {t('competitorData.comments.summary', { comments: number.format(summary.comments), replies: number.format(summary.replies), agreeing: number.format(summary.people_agreeing) })}
                    {summary.held_back_for_safety > 0 && ` · ${t('competitorData.comments.heldBack', { count: number.format(summary.held_back_for_safety) })}`}
                  </p>
                )}
                <ul className="competitor-comments">
                  {comments.map((comment) => <Comment key={comment.id} comment={comment} t={t} number={number} date={date} />)}
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
