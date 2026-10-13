import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ExternalLink } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { Panel, Pill, StateBlock } from '../../../shared/components/apex/Apex.jsx';
import { discoveryApi } from '../api/discoveryApi.js';

const RELATIONSHIPS = ['DIRECT', 'INDIRECT', 'RELATED', 'UNVERIFIED'];
const BANDS = ['under_1km', '1_3km', '3_5km', '5_10km', 'over_10km'];
const TONE = { DIRECT: 'success', INDIRECT: 'accent', RELATED: 'neutral', UNVERIFIED: 'warning' };

// The shape of the market from what the scans stored: how many businesses
// compete and how closely, what kinds, how far, how many publish prices,
// and the published prices found for each of the company's products. Only
// counts and ranges over stored, source-backed rows (backend market_structure.py).
export function MarketStructure() {
  const { t, locale } = useI18n();
  const query = useQuery({ queryKey: ['market-structure'], queryFn: discoveryApi.marketStructure, staleTime: 60_000 });
  const number = useMemo(() => new Intl.NumberFormat(locale, { maximumFractionDigits: 3 }), [locale]);

  if (query.isPending) return <Panel><StateBlock kind="loading" compact title={t('common.loading')} /></Panel>;
  if (query.isError) return <Panel><StateBlock kind="error" compact title={t('discovery.error')} onRetry={() => query.refetch()} retryLabel={t('demandApex.actions.retry')} /></Panel>;
  const data = query.data;
  if (!data.businesses) {
    return <Panel eyebrow={t('structure.eyebrow')} title={t('structure.title')}><StateBlock compact title={t('structure.empty')} description={t('structure.emptyHint')} /></Panel>;
  }
  const maxBand = Math.max(1, ...BANDS.map((b) => data.distance_bands?.[b] || 0));
  return (
    <Panel eyebrow={t('structure.eyebrow')} title={t('structure.title')} subtitle={t('structure.subtitle', { count: number.format(data.businesses) })}>
      <div className="market-structure">
        <section>
          <h3>{t('structure.howClose')}</h3>
          <div className="market-structure__pills">
            {RELATIONSHIPS.filter((k) => data.by_relationship?.[k]).map((k) => (
              <Pill key={k} tone={TONE[k]}>{t(`discovery.relationship.${k}`)} · {number.format(data.by_relationship[k])}</Pill>
            ))}
          </div>
          <p className="apex-muted">{t('structure.chains', { count: number.format(data.chains) })}</p>
        </section>
        <section>
          <h3>{t('structure.kinds')}</h3>
          <ul className="market-structure__list">
            {data.top_categories.map((c) => <li key={c.category}><span dir="auto">{c.category}</span><strong>{number.format(c.count)}</strong></li>)}
          </ul>
        </section>
        <section>
          <h3>{t('structure.distance')}</h3>
          <ul className="market-structure__bars">
            {BANDS.map((band) => (
              <li key={band}>
                <span>{t(`structure.bands.${band}`)}</span>
                <span className="market-structure__bar" aria-hidden="true"><span style={{ width: `${((data.distance_bands?.[band] || 0) / maxBand) * 100}%` }} /></span>
                <strong>{number.format(data.distance_bands?.[band] || 0)}</strong>
              </li>
            ))}
          </ul>
        </section>
        <section>
          <h3>{t('structure.websites')}</h3>
          <p>{t('structure.websitesValue', { known: number.format(data.websites.known), read: number.format(data.websites.read), priced: number.format(data.websites.with_prices) })}</p>
        </section>
      </div>
      <section className="market-structure__prices">
        <h3>{t('structure.prices')}</h3>
        {data.product_prices.length === 0
          ? <p className="apex-muted">{t('structure.noPrices')}</p>
          : (
            <table className="apex-table">
              <thead><tr><th>{t('structure.product')}</th><th>{t('structure.yours')}</th><th>{t('structure.range')}</th><th>{t('structure.median')}</th><th>{t('structure.seenAt')}</th></tr></thead>
              <tbody>
                {data.product_prices.map((p) => (
                  <tr key={p.product}>
                    <td dir="auto">{p.product}</td>
                    <td>{p.currency} {number.format(p.your_price)} <Pill tone={p.position === 'above' ? 'warning' : p.position === 'below' ? 'success' : 'neutral'}>{t(`structure.position.${p.position}`)}</Pill></td>
                    <td>{p.currency} {number.format(p.min)}{p.max !== p.min ? ` – ${number.format(p.max)}` : ''}</td>
                    <td>{p.currency} {number.format(p.median)} <span className="apex-muted">({t('structure.competitors', { count: p.count })})</span></td>
                    <td>
                      {p.prices.slice(0, 3).map((x) => (
                        <a key={`${x.competitor}-${x.price}`} className="apex-pill apex-pill--neutral" href={x.source_url} target="_blank" rel="noreferrer noopener" dir="auto">
                          {x.competitor} · {number.format(x.price)}<ExternalLink size={10} aria-hidden="true" />
                        </a>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      </section>
      <p className="apex-source">{t('structure.provenance')}</p>
    </Panel>
  );
}

export default MarketStructure;
