import { useState } from 'react';
import { Link2, RotateCcw, Unlink } from 'lucide-react';
import { useAuth } from '../../../app/providers/AuthProvider.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { ApexButton, Panel, Pill } from '../../../shared/components/apex/Apex.jsx';
import { canReviewPrices, chooseableItems } from '../api/competitorDataApi.js';
import { useCompetitorMatches, useMatchActions } from '../hooks/useCompetitorData.js';

// Their price is five times (or a fifth of) yours: usually a different size or pack, worth a second look.
function priceGap(match) {
  if (!match.your_price || !match.their_price || (match.their_currency && match.their_currency !== match.currency)) return false;
  const ratio = match.their_price / match.your_price;
  return ratio >= 5 || ratio <= 0.2;
}

function money(locale, value, currency) {
  if (value == null) return '—';
  if (!currency) return new Intl.NumberFormat(locale, { maximumFractionDigits: 3 }).format(value);
  try { return new Intl.NumberFormat(locale, { style: 'currency', currency }).format(value); } catch { return `${value} ${currency}`; }
}

// Which of this competitor's items is which of your products. The automatic match can be wrong ("Mansaf tray" is not
// "Mansaf plate") and a wrong match feeds a wrong price comparison, so an owner / admin can say "not this item", pick the
// right item, or go back to automatic. Decisions are kept across every later read of the competitor's site.
export function ProductMatches({ competitorId }) {
  const { t, locale } = useI18n();
  const { roles } = useAuth();
  const canChange = canReviewPrices(roles);
  const query = useCompetitorMatches(competitorId);
  const actions = useMatchActions(competitorId);
  const [choosing, setChoosing] = useState(null); // product_id being re-matched
  const [pick, setPick] = useState('');
  const [problem, setProblem] = useState(null);
  const data = query.data;
  const busy = actions.reject.isPending || actions.choose.isPending || actions.clear.isPending;
  const fail = (error) => setProblem(error?.response?.status === 403 ? 'forbidden' : error?.response?.status === 422 ? 'refused' : 'failed');
  const run = (mutation, variables, after) => {
    setProblem(null);
    mutation.mutate(variables, { onSuccess: () => { setChoosing(null); setPick(''); after?.(); }, onError: fail });
  };

  if (query.isPending) return null;
  if (query.isError || !data) return null;
  if (data.matches.length === 0 && data.rejected.length === 0) return null; // no matched items: nothing to correct

  return (
    <Panel eyebrow={t('productMatches.eyebrow')} title={t('productMatches.title')} subtitle={t('productMatches.subtitle')}>
      {data.matches.length > 0 && (
        <div className="apex-table-wrap"><table className="apex-table intel-prices">
          <thead><tr>
            <th>{t('productMatches.yourProduct')}</th><th>{t('productMatches.theirItem')}</th>
            <th className="apex-table__num">{t('market.detail.theirPrice')}</th>{canChange && <th>{t('intel.review.column')}</th>}
          </tr></thead>
          <tbody>{data.matches.map((m) => {
            const options = chooseableItems(data.items, { currency: m.currency }, m.item);
            return (
              <tr key={m.mapping_id}>
                <td dir="auto">{m.product}<div className="apex-muted">{t('productMatches.yourPrice', { price: money(locale, m.your_price, m.currency) })}</div></td>
                <td dir="auto">{m.item}{m.owner_chosen && <> <Pill tone="success">{t('productMatches.chosenByYou')}</Pill></>}</td>
                <td className="apex-table__num">
                  {money(locale, m.their_price, m.their_currency || m.currency)}
                  {priceGap(m) && <div className="apex-muted price-origin__was price-origin__check">{t('productMatches.priceGap')}</div>}
                </td>
                {canChange && (
                  <td>
                    {choosing === m.product_id ? (
                      <form className="price-review price-review--edit" onSubmit={(event) => { event.preventDefault(); if (pick) run(actions.choose, { productId: m.product_id, intelId: pick }); }}>
                        <label className="sr-only" htmlFor={`pick-${m.product_id}`}>{t('productMatches.pickItem')}</label>
                        <select id={`pick-${m.product_id}`} className="apex-select" value={pick} onChange={(event) => setPick(event.target.value)} autoFocus>
                          <option value="">{t('productMatches.pickItem')}</option>
                          {options.map((item) => <option key={item.intel_id} value={item.intel_id}>{item.name} · {money(locale, item.price, item.currency)}</option>)}
                        </select>
                        <ApexButton size="sm" type="submit" disabled={!pick} loading={actions.choose.isPending}>{t('intel.review.save')}</ApexButton>
                        <ApexButton size="sm" variant="ghost" onClick={() => { setChoosing(null); setProblem(null); }}>{t('intel.review.cancel')}</ApexButton>
                      </form>
                    ) : (
                      <div className="price-review">
                        <ApexButton size="sm" variant="ghost" icon={Unlink} disabled={busy} title={t('productMatches.notSameHint')} onClick={() => run(actions.reject, m.product_id)}>{t('productMatches.notSame')}</ApexButton>
                        {options.length > 0 && <ApexButton size="sm" variant="ghost" icon={Link2} disabled={busy} onClick={() => { setChoosing(m.product_id); setPick(''); setProblem(null); }}>{t('productMatches.choose')}</ApexButton>}
                        {m.owner_chosen && <ApexButton size="sm" variant="ghost" icon={RotateCcw} disabled={busy} onClick={() => run(actions.clear, m.product_id)}>{t('productMatches.auto')}</ApexButton>}
                      </div>
                    )}
                  </td>
                )}
              </tr>
            );
          })}</tbody>
        </table></div>
      )}
      {data.rejected.length > 0 && (
        <>
          <h3 className="competitor-facts__heading">{t('productMatches.rejectedTitle')}</h3>
          <ul className="intel-list">{data.rejected.map((r) => (
            <li key={`${r.product_id}-${r.item}`}>
              <span dir="auto">{t('productMatches.rejectedLine', { item: r.item, product: r.product })}</span>
              {canChange && <> <ApexButton size="sm" variant="ghost" icon={RotateCcw} disabled={busy} onClick={() => run(actions.clear, r.product_id)}>{t('productMatches.auto')}</ApexButton></>}
            </li>
          ))}</ul>
        </>
      )}
      {problem && <p className="market-scan__note is-error" role="alert">{t(`productMatches.problem.${problem}`)}</p>}
      {!canChange && <p className="apex-source">{t('productMatches.ownerOnly')}</p>}
    </Panel>
  );
}

export default ProductMatches;
