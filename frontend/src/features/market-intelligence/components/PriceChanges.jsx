import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { TrendingDown, TrendingUp } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { Panel, Pill, StateBlock } from '../../../shared/components/apex/Apex.jsx';
import { changeLabel, intelOrigin, sortChanges } from '../api/competitorDataApi.js';
import { usePriceChanges, useRecentPriceChanges } from '../hooks/useCompetitorData.js';

const money = (locale) => (value, currency) => {
  if (!currency) return new Intl.NumberFormat(locale, { maximumFractionDigits: 3 }).format(value);
  try { return new Intl.NumberFormat(locale, { style: 'currency', currency }).format(value); } catch { return `${value} ${currency}`; }
};

// One price move: "Mansaf 8.50 -> 9.50 (+11.8%)", when, and how it was read. A drop is good news for the buyer and
// bad for the seller, so the colour only says direction (a falling price is highlighted: it is the one that costs the owner sales).
function ChangeRow({ change, showCompetitor, t, date, fmt, pct }) {
  const down = change.direction === 'down';
  const Icon = down ? TrendingDown : TrendingUp;
  const origin = change.channel || (change.origin && change.origin !== 'website' ? change.origin : null);
  return (
    <li className={`price-change ${down ? 'is-down' : 'is-up'}`}>
      <Icon size={16} aria-hidden="true" />
      <div className="price-change__body">
        <strong dir="auto">{change.item}</strong>
        {showCompetitor && (
          <> <Link to={routePaths.marketCompetitorDetail.replace(':competitorId', change.competitor_id)} dir="auto">{change.competitor}</Link></>
        )}
        <div className="price-change__prices">
          <span>{fmt(change.old_price, change.currency)}</span> <span aria-hidden="true">→</span> <span className="sr-only">{t('priceChanges.to')}</span>
          <strong>{fmt(change.new_price, change.currency)}</strong>
          {change.change_pct != null && <Pill tone={down ? 'warning' : 'neutral'}><span dir="ltr">{changeLabel(change.change_pct, pct)}</span></Pill>}
        </div>
        <div className="apex-muted price-change__meta">
          {t('priceChanges.on', { date: date.format(new Date(change.changed_at)) })}
          {origin && <> · {t(`intel.origin.${intelOrigin({ extracted_by: change.origin })}`, { defaultValue: String(origin) })}</>}
          {!change.reliable && <> · <span className="price-origin__check">{t('priceChanges.uncertain')}</span></>}
        </div>
      </div>
    </li>
  );
}

function useFormatters() {
  const { locale } = useI18n();
  return useMemo(() => ({
    date: new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }),
    fmt: money(locale),
    pct: new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }),
  }), [locale]);
}

// Price moves on one competitor's own menu, site and posts. Changes between two weak reads (picture, caption or AI
// reads) are hidden until asked for, so a misread digit is never presented as the competitor changing a price.
export function PriceChanges({ competitorId }) {
  const { t } = useI18n();
  const { date, fmt, pct } = useFormatters();
  const [includeUncertain, setIncludeUncertain] = useState(false);
  const query = usePriceChanges(competitorId, { days: 90, includeUnreliable: includeUncertain });
  const changes = sortChanges(query.data);
  return (
    <Panel
      eyebrow={t('priceChanges.eyebrow')}
      title={t('priceChanges.title')}
      subtitle={t('priceChanges.subtitle')}
      actions={(
        <label className="price-changes__toggle">
          <input type="checkbox" checked={includeUncertain} onChange={(event) => setIncludeUncertain(event.target.checked)} />
          <span>{t('priceChanges.includeUncertain')}</span>
        </label>
      )}
    >
      {query.isPending ? <StateBlock kind="loading" compact title={t('common.loading')} />
        : query.isError ? <StateBlock kind="error" compact title={t('priceChanges.error')} onRetry={() => query.refetch()} retryLabel={t('demandApex.actions.retry')} />
          : changes.length === 0 ? <StateBlock compact title={t('priceChanges.none')} description={t('priceChanges.noneHint')} />
            : <ul className="price-changes">{changes.map((change) => <ChangeRow key={`${change.item_key}-${change.changed_at}-${change.currency}`} change={change} t={t} date={date} fmt={fmt} pct={pct} />)}</ul>}
    </Panel>
  );
}

// The latest price moves across every competitor, for the Market page.
export function RecentPriceChanges() {
  const { t } = useI18n();
  const { date, fmt, pct } = useFormatters();
  const query = useRecentPriceChanges({ days: 30, limit: 8 });
  const changes = sortChanges(query.data);
  if (query.isPending || query.isError || changes.length === 0) return null; // nothing to say is better than an empty box
  return (
    <Panel eyebrow={t('priceChanges.eyebrow')} title={t('priceChanges.recentTitle')} subtitle={t('priceChanges.recentSubtitle')}>
      <ul className="price-changes">{changes.map((change) => <ChangeRow key={`${change.competitor_id}-${change.item_key}-${change.changed_at}`} change={change} showCompetitor t={t} date={date} fmt={fmt} pct={pct} />)}</ul>
    </Panel>
  );
}

export default PriceChanges;
