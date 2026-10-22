import { useMemo, useState } from 'react';
import { ExternalLink } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { Pill } from '../../../shared/components/apex/Apex.jsx';
import '../styles/Pricing.css';
import { safeHref } from '../../../shared/lib/safeUrl.js';

// Links come from scraped pages: only http(s) is ever followed.

export const TIERS = ['EXACT', 'EQUIVALENT', 'SIMILAR', 'ADDED_VALUE'];
const TIER_TONE = { EXACT: 'success', EQUIVALENT: 'accent', SIMILAR: 'neutral', ADDED_VALUE: 'violet' };
const PREMIUM_TONE = { underpriced: 'warning', within_range: 'success', above_range: 'warning' };
const KNOWN_MARKERS = new Set(['extra', 'double', 'triple', 'premium', 'loaded', 'combo']);

// How far you are from a price, in words: positive = you are dearer.
export function PositionPill({ pct, t, number }) {
  if (pct == null) return <span className="apex-muted">—</span>;
  if (Math.abs(pct) < 2) return <Pill tone="neutral">{t('pricing.ladder.inLine')}</Pill>;
  return <Pill tone={pct > 0 ? 'warning' : 'success'}>{t(pct > 0 ? 'pricing.ladder.above' : 'pricing.ladder.below', { pct: number.format(Math.abs(pct)) })}</Pill>;
}

export function TierPill({ tier, t }) {
  return <Pill tone={TIER_TONE[tier] || 'neutral'}>{t(`pricing.ladder.tier.${tier}.name`)}</Pill>;
}

// The ladder for one product (GET /pricing/comparisons/{id}): four tiers, each competitor item with its own price,
// the comparable price (scaled to your quantity when it differs), how far you are from it, and why it sits in that
// tier. A tier with nothing in it says so - the tiers are the explanation of how the market was read.
export function PriceLadder({ ladder, onDecide, onSetBand, busy = false }) {
  const { t, locale } = useI18n();
  const [bandInput, setBandInput] = useState('');
  const bandValid = bandInput !== '' && Number(bandInput) >= 5 && Number(bandInput) <= 300;
  const number = useMemo(() => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }), [locale]);
  const date = useMemo(() => new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }), [locale]);
  const money = (amount) => (amount == null ? '—' : new Intl.NumberFormat(locale, { style: 'currency', currency: ladder.currency }).format(amount));
  const list = (values) => values.map((value) => (KNOWN_MARKERS.has(value) ? t(`pricing.ladder.marker.${value}`) : value)).join(', ');

  const reasonText = (reason) => {
    switch (reason.code) {
      case 'variant_differs': return t('pricing.ladder.reason.variant_differs', { own: list(reason.own || []) || '—', competitor: list(reason.competitor || []) || '—' });
      case 'own_has_extras': return t('pricing.ladder.reason.own_has_extras', { extras: list(reason.extras || []) });
      case 'competitor_has_extras': return t('pricing.ladder.reason.competitor_has_extras', { extras: list(reason.extras || []) });
      case 'quantity_scaled': return t('pricing.ladder.reason.quantity_scaled', { factor: number.format(reason.factor), own: reason.own, competitor: reason.competitor });
      case 'quantity_pro_rata': return t('pricing.ladder.reason.quantity_pro_rata', { own: reason.own, competitor: reason.competitor });
      case 'specificity_unclear': return t(`pricing.ladder.reason.specificity_${reason.side === 'own' ? 'own' : 'competitor'}`, { words: list(reason.words || []) });
      case 'ai_judged': return t(`pricing.ladder.reason.ai_${reason.verdict === 'addition' ? 'addition' : 'variant'}`, { words: list(reason.words || []) });
      case 'owner_decision': return t(`pricing.ladder.reason.owner_${reason.verdict === 'addition' ? 'addition' : 'variant'}`);
      case 'size_differs': case 'quantity_unit_assumed': case 'quantity_not_stated_on_one_side': case 'recorded_price':
        return t(`pricing.ladder.reason.${reason.code}`);
      default: return null;
    }
  };

  const headline = ladder.headline;
  return (
    <div className="price-ladder">
      {headline ? (
        <p className="price-ladder__headline">
          {headline.position_pct == null || Math.abs(headline.position_pct) < 2
            ? t('pricing.ladder.headlineInLine', { count: headline.count, tier: t(`pricing.ladder.tier.${headline.tier}.name`).toLowerCase(), median: money(headline.median_comparable) })
            : t(headline.position_pct > 0 ? 'pricing.ladder.headlineAbove' : 'pricing.ladder.headlineBelow', {
              count: headline.count, tier: t(`pricing.ladder.tier.${headline.tier}.name`).toLowerCase(),
              pct: number.format(Math.abs(headline.position_pct)), median: money(headline.median_comparable),
            })}
        </p>
      ) : <p className="price-ladder__headline apex-muted">{t('pricing.ladder.noneAtAll')}</p>}

      {ladder.added_value_guidance ? (
        <div className="price-ladder__guidance" data-testid="added-value-guidance">
          {t('pricing.ladder.guidance.text', {
            base: money(ladder.added_value_guidance.base_price), low: money(ladder.added_value_guidance.range_low),
            high: money(ladder.added_value_guidance.range_high), band: number.format(ladder.added_value_guidance.band_pct),
          })}{' '}
          {t(`pricing.ladder.guidance.position.${ladder.added_value_guidance.position}`)}{' '}
          <span className="apex-muted">
            {ladder.added_value_guidance.band_source === 'owner' ? t('pricing.ladder.guidance.owner')
              : ladder.added_value_guidance.band_source === 'observed'
                ? t('pricing.ladder.guidance.observed', { count: ladder.added_value_guidance.band_samples })
                : t('pricing.ladder.guidance.default')}
          </span>
          {onSetBand && (
            <form className="price-ladder__band-editor" onSubmit={(event) => {
              event.preventDefault();
              if (!bandValid) return;
              onSetBand(ladder.category ?? null, Number(bandInput));
              setBandInput('');
            }}>
              <label>
                <span className="apex-muted">{t('pricing.ladder.guidance.setLabel')}</span>{' '}
                <input type="number" inputMode="decimal" min="5" max="300" step="1" value={bandInput} onChange={(event) => setBandInput(event.target.value)} />
              </label>{' '}
              <button type="submit" className="price-ladder__link" disabled={busy || !bandValid}>{t('pricing.ladder.guidance.save')}</button>
              {ladder.added_value_guidance.band_source === 'owner' && (
                <button type="button" className="price-ladder__link" disabled={busy} onClick={() => onSetBand(ladder.category ?? null, null)}>{t('pricing.ladder.guidance.clear')}</button>
              )}
            </form>
          )}
        </div>
      ) : null}

      {TIERS.map((tier) => {
        const data = ladder.tiers[tier];
        return (
          <section key={tier} className="price-ladder__tier" aria-label={t(`pricing.ladder.tier.${tier}.name`)}>
            <header className="price-ladder__tier-head">
              <TierPill tier={tier} t={t} />
              <span className="apex-muted">{t(`pricing.ladder.tier.${tier}.hint`)}</span>
              <span className="price-ladder__count">{number.format(data.count)}</span>
            </header>
            {data.count === 0 ? <p className="price-ladder__empty apex-muted">{t('pricing.ladder.tierEmpty')}</p> : (
              <div className="apex-table-wrap" role="region" aria-label={t(`pricing.ladder.tier.${tier}.name`)} tabIndex={0}>
                <table className="apex-table">
                  <thead><tr>
                    <th>{t('pricing.ladder.competitor')}</th>
                    <th className="apex-table__num">{t('pricing.ladder.theirPrice')}</th>
                    <th className="apex-table__num">{tier === 'ADDED_VALUE' ? t('pricing.ladder.basePrice') : t('pricing.ladder.comparable')}</th>
                    <th>{tier === 'ADDED_VALUE' ? t('pricing.ladder.premium') : t('pricing.ladder.vsYou')}</th>
                    <th>{t('pricing.ladder.why')}</th>
                  </tr></thead>
                  <tbody>
                    {data.items.map((item) => (
                      <tr key={`${tier}-${item.competitor_id}`}>
                        <td>
                          <strong dir="auto">{item.competitor_name}</strong>
                          {item.item_name && <div className="apex-muted" dir="auto">{item.item_name}</div>}
                        </td>
                        <td className="apex-table__num">{money(item.competitor_price)}</td>
                        <td className="apex-table__num apex-table__primary">
                          {money(item.comparable_price)}
                          {item.scale_factor !== 1 && <div className="apex-muted">{t('pricing.ladder.scaled', { factor: number.format(item.scale_factor) })}</div>}
                        </td>
                        <td>
                          {tier === 'ADDED_VALUE' && item.premium ? (
                            <>
                              <Pill tone={PREMIUM_TONE[item.premium.status] || 'neutral'}>{`${item.premium.premium_pct > 0 ? '+' : ''}${number.format(item.premium.premium_pct)}%`}</Pill>
                              <div className="apex-muted">{t(`pricing.ladder.premiumStatus.${item.premium.status}`, { band: number.format(item.premium.band_pct) })}</div>
                            </>
                          ) : (
                            <>
                              <PositionPill pct={item.price_delta_pct} t={t} number={number} />
                              {tier === 'SIMILAR' && item.direction !== 'same' && <div className="apex-muted">{t(`pricing.ladder.direction.${item.direction}`)}</div>}
                            </>
                          )}
                        </td>
                        <td className="price-ladder__why">
                          {item.reasons.map(reasonText).filter(Boolean).map((text) => <div key={text}>{text}</div>)}
                          {onDecide && item.item_name && (
                            <div className="price-ladder__decide" role="group" aria-label={t('pricing.ladder.decide.title')}>
                              {item.method === 'OWNER' && <span className="price-ladder__by-you">{t('pricing.ladder.decide.byYou')}</span>}
                              {tier !== 'ADDED_VALUE' && <button type="button" disabled={busy} onClick={() => onDecide(item, 'ADDITION')}>{t('pricing.ladder.decide.addition')}</button>}
                              {(tier !== 'SIMILAR' || item.reasons.some((r) => r.code === 'specificity_unclear')) && <button type="button" disabled={busy} onClick={() => onDecide(item, 'VARIANT')}>{t('pricing.ladder.decide.variant')}</button>}
                              <button type="button" disabled={busy} onClick={() => onDecide(item, 'NOT_COMPARABLE')}>{t('pricing.ladder.decide.notComparable')}</button>
                              {item.method === 'OWNER' && <button type="button" disabled={busy} onClick={() => onDecide(item, null)}>{t('pricing.ladder.decide.undo')}</button>}
                            </div>
                          )}
                          <div className="apex-muted">
                            {item.observed_at ? date.format(new Date(item.observed_at)) : null}
                            {safeHref(item.source_url) && <a className="apex-inline-link" href={safeHref(item.source_url)} target="_blank" rel="noreferrer noopener" aria-label={t('pricing.ladder.openSource', { name: item.competitor_name })}><ExternalLink size={12} aria-hidden="true" /></a>}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        );
      })}
      <p className="price-ladder__note apex-muted">{t('pricing.ladder.note')}</p>
    </div>
  );
}

export default PriceLadder;
