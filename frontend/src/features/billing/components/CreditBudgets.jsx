import { Bot, Database } from 'lucide-react';
import { getCreditBudgetState } from '../utils/creditBudgetState.js';

const BUDGETS = [
  { key: 'data', icon: Database },
  { key: 'ai', icon: Bot },
];

// Data Credits and AI Credits as two separate budgets (from /billing/subscription's
// `credits`): what is used, held for work in progress, left, and when it renews.
// Costs and provider prices are never shown - only credits.
export function CreditBudgets({ credits, locale, t, formatDate }) {
  const budgets = credits || {};
  const number = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 });
  return <div className="billing-usage-grid billing-credit-grid">{BUDGETS.map(({ key, icon: Icon }) => {
    const budget = budgets[key];
    const state = getCreditBudgetState(budget);
    const limit = budget?.limit;
    const used = Number.isFinite(budget?.consumed) && Number.isFinite(budget?.reserved)
      ? budget.consumed + budget.reserved
      : 0;
    const percent = typeof limit === 'number' && limit > 0 ? Math.min(100, Math.max(0, (used / limit) * 100)) : 0;
    const renews = budget?.resets_on ? formatDate(budget.resets_on) : '';
    return <article className={`billing-usage-card is-${state}`} key={key}>
      <header><strong><Icon size={13} aria-hidden="true" /> {t(`billing.management.credits.${key}`)}</strong>
        <span>{t(`billing.management.usageState.${state}`)}</span></header>
      {state === 'notIncluded' || state === 'unknown'
        ? <p role={state === 'unknown' ? 'status' : undefined}>{t(`billing.management.credits.${state === 'unknown' ? 'unavailable' : 'notIncluded'}`)}</p>
        : <>
          <p><bdi>{number.format(used)}</bdi> <small>/ <bdi>{limit === null ? '∞' : number.format(limit)}</bdi></small></p>
          {typeof limit === 'number' && limit > 0 && <div className="billing-usage-progress" role="progressbar" aria-label={t(`billing.management.credits.${key}`)} aria-valuemin="0" aria-valuemax={limit} aria-valuenow={Math.min(used, limit)}><span style={{ width: `${percent}%` }} /></div>}
          <small className="billing-credit-line">{limit === null ? '' : t('billing.management.credits.remaining', { remaining: number.format(budget.remaining ?? 0) })}{budget.reserved > 0 ? ` · ${t('billing.management.credits.inProgress', { reserved: number.format(budget.reserved) })}` : ''}</small>
          {renews && <small className="billing-credit-line">{t('billing.management.credits.renews', { date: renews })}</small>}
          {state === 'approaching' && <small className="billing-credit-line" role="status">{t('billing.management.credits.warning', { percent: number.format(budget.percent_used ?? 0) })}</small>}
          {state === 'reached' && <small className="billing-credit-line" role="alert">{t('billing.management.credits.exhausted')} {t('billing.management.credits.exhaustedOptions', { date: renews })}</small>}
        </>}
      <small className="billing-credit-help">{t(`billing.management.credits.${key}Help`)}</small>
    </article>;
  })}</div>;
}

// The latest operations that used credits, and whether each was charged.
export function UsageHistory({ items, locale, t }) {
  const when = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' });
  const number = new Intl.NumberFormat(locale, { maximumFractionDigits: 2 });
  if (!items?.length) return <p className="billing-usage-unavailable">{t('billing.management.credits.historyEmpty')}</p>;
  // An operation or status this screen doesn't name yet reads as "Other" / its code.
  const known = (key, fallback) => { const text = t(key); return text === key ? fallback : text; };
  const label = (operation) => known(`billing.management.credits.operations.${operation}`, t('billing.management.credits.operations.other'));
  return <div className="billing-comparison-wrap" tabIndex={0} role="region" aria-label={t('common.scrollableTable')}>
    <table className="billing-comparison-table billing-usage-history">
      <thead><tr>{['when', 'what', 'budget', 'credits', 'status'].map((c) => <th key={c}>{t(`billing.management.credits.historyColumns.${c}`)}</th>)}</tr></thead>
      <tbody>{items.map((item, index) => <tr key={`${item.operation_id}-${index}`}>
        <td>{when.format(new Date(item.at))}</td>
        <td>{label(item.operation)}</td>
        <td>{t(`billing.management.credits.${item.budget === 'ai' ? 'ai' : 'data'}`)}</td>
        <td><bdi>{number.format(item.credits)}</bdi></td>
        <td>{known(`billing.management.credits.statuses.${item.status}`, item.status)}</td>
      </tr>)}</tbody>
    </table>
  </div>;
}
