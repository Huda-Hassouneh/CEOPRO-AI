import { useId } from 'react';
import { ArrowUpRight, BarChart3, Boxes, Check, Database, FileCheck2, FileSpreadsheet, FileText, Globe2, MessageCircle, ShoppingBag, Sparkles, TrendingUp } from 'lucide-react';
import { LANDING_DEMO as demo } from '../data/demoData.js';
import { DemoCaption, useLanding, VisualHeader } from './LandingPrimitives.jsx';

export function TrendChart({ forecast = false, compact = false }) {
  const { t, n } = useLanding();
  const gradient = useId();
  const forecastY = 240 - demo.demand.expected / 4;
  const upperY = 240 - demo.demand.high / 4;
  const lowerY = 240 - demo.demand.low / 4;
  return <div className={`lp-trend-chart ${compact ? 'lp-trend-chart--compact' : ''}`}>
    <svg viewBox="0 0 540 220" role="img" aria-label={t(forecast ? 'demand.visualTitle' : 'hero.legend')}>
      <defs><linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--ceopro-primary)" stopOpacity=".18" /><stop offset="100%" stopColor="var(--ceopro-primary)" stopOpacity="0" /></linearGradient></defs>
      {[40, 90, 140, 190].map((y, i) => <g key={y}><line x1="38" y1={y} x2="526" y2={y} stroke="var(--ceopro-border)" strokeDasharray="3 5" /><text x="28" y={y + 4} textAnchor="end">{n(800 - i * 200)}</text></g>)}
      {forecast ? <>
        <path d={`M300 115 C370 104 430 88 526 ${upperY} L526 ${lowerY} C430 113 370 137 300 130Z`} fill="var(--ceopro-primary)" opacity=".12" />
        <path d="M38 178 C80 170 90 130 125 140 S178 167 205 126 S260 132 300 122" fill="none" stroke="var(--ceopro-primary)" strokeWidth="3" />
        <path d={`M300 122 C370 121 440 96 526 ${forecastY}`} fill="none" stroke="var(--ceopro-primary)" strokeWidth="3" strokeDasharray="7 5" />
        <line x1="300" y1="20" x2="300" y2="190" stroke="var(--ceopro-border-soft)" strokeDasharray="4 5" />
        <circle cx="526" cy={forecastY} r="5" fill="var(--ceopro-primary)" />
      </> : <>
        <path d="M38 169 C70 185 96 119 125 139 S170 155 200 114 S245 137 276 91 S310 105 350 76 S405 88 445 48 S485 59 526 23 L526 190 L38 190Z" fill={`url(#${gradient})`} />
        <path d="M38 169 C70 185 96 119 125 139 S170 155 200 114 S245 137 276 91 S310 105 350 76 S405 88 445 48 S485 59 526 23" fill="none" stroke="var(--ceopro-primary)" strokeWidth="3" />
        <circle cx="445" cy="48" r="5" fill="var(--ceopro-primary)" stroke="white" strokeWidth="3" />
      </>}
      {[1, 2, 3, 4, 5, 6].map((week, index) => <text key={week} x={40 + index * 96} y="215" textAnchor="middle">{t('demand.week', { n: n(week) })}</text>)}
    </svg>
    {forecast && <div className="lp-chart-legend"><span><i />{t('demand.history')}</span><span><i className="lp-dashed" />{t('demand.forecast')}</span><span><i className="lp-band" />{t('demand.uncertainty')}</span></div>}
  </div>;
}

export function HeroVisual() {
  const { t, n, money, percent } = useLanding();
  return <div className="lp-hero-art"><div className="lp-orbit lp-orbit-one" /><div className="lp-orbit lp-orbit-two" /><figure className="lp-browser">
    <div className="lp-browser-bar"><span aria-hidden="true"><i /><i /><i /></span><small dir="ltr">CEOPRO AI</small><span className="lp-preview-label">{t('common.sample')}</span></div>
    <div className="lp-browser-content"><VisualHeader title={t('hero.overview')} subtitle={t('hero.period')} /><div className="lp-hero-metrics">{[['revenue', money(demo.revenue)], ['sales', n(demo.sales)], ['growth', `+${percent(demo.growth)}`]].map(([key, value]) => <div key={key}><span>{t(`hero.${key}`)}</span><strong><bdi>{value}</bdi></strong></div>)}</div>
      <div className="lp-hero-chart"><span>{t('hero.legend')}</span><TrendChart compact /></div>
      <div className="lp-hero-bottom"><div><Boxes size={17} /><span>{t('hero.inventory')}</span><strong>{percent(demo.inventory)}</strong></div><div><MessageCircle size={17} /><span>{t('hero.sentiment')}</span><strong>{percent(demo.sentiment.positive)}</strong></div></div>
      <DemoCaption />
    </div>
  </figure><div className="lp-floating lp-floating--forecast"><span className="lp-icon"><TrendingUp size={20} /></span><div><small>{t('hero.forecast')}</small><strong>{n(demo.demand.expected)} <small>{t('common.units')}</small></strong></div><ArrowUpRight size={20} /></div><div className="lp-floating lp-floating--insight"><Sparkles size={19} /><div><strong>{t('hero.insight')}</strong><small>{t('hero.insightText')}</small></div></div></div>;
}

export function MarketVisual() {
  const { t, money, n } = useLanding();
  return <figure className="lp-visual lp-market-visual"><VisualHeader title={t('market.visualTitle')} subtitle={t('market.product')} /><div className="lp-table-wrap" tabIndex={0} role="region" aria-label={t('market.visualTitle')}><table><thead><tr>{['competitor', 'price', 'availability', 'sentiment'].map((key) => <th key={key} scope="col">{t(`market.${key}`)}</th>)}</tr></thead><tbody>{demo.competitors.map((row, index) => <tr key={row.key}><th scope="row"><span className={`lp-competitor-avatar lp-competitor-avatar--${index}`} aria-hidden="true">{n(index + 1)}</span>{t(`market.${row.key}`)}</th><td><bdi>{money(row.price)}</bdi></td><td><span className={row.availability === 'inStock' ? 'lp-status' : 'lp-status lp-status--neutral'}>{t(`market.${row.availability}`)}</span></td><td>{t(`market.${row.sentiment}`)}</td></tr>)}</tbody></table></div><div className="lp-market-summary"><span><Check size={14} />{t('market.matches')}</span><div><small>{t('market.score')}</small><strong><bdi>{n(8.4)} / {n(10)}</bdi></strong></div><div><small>{t('market.composite')}</small><strong><bdi>{n(82)} / {n(100)}</bdi></strong></div></div><DemoCaption /></figure>;
}

export function DemandVisual() {
  const { t, n } = useLanding();
  return <figure className="lp-visual lp-demand-visual"><VisualHeader title={t('demand.visualTitle')} subtitle={t('demand.target')} /><div className="lp-demand-main"><div><span>{t('demand.expected')}</span><strong>{n(demo.demand.expected)} <small>{t('common.units')}</small></strong></div><div><span>{t('demand.range')}</span><b><bdi>{n(demo.demand.low)}–{n(demo.demand.high)}</bdi></b></div></div><TrendChart forecast /><div className="lp-three-stats">{['stock', 'reorder', 'safety'].map((key) => <div key={key}><span>{t(`demand.${key}`)}</span><strong>{n(demo.demand[key])}</strong></div>)}</div><DemoCaption /></figure>;
}

export function PricingVisual() {
  const { t, money, n, percent } = useLanding();
  const pricing = demo.pricing;
  return <figure className="lp-visual lp-pricing-visual"><VisualHeader title={t('pricingIntel.visualTitle')} /><div className="lp-price-comparison"><div><span>{t('pricingIntel.current')}</span><strong><bdi>{money(pricing.current)}</bdi></strong></div><span className="lp-price-arrow" aria-hidden="true">→</span><div className="lp-suggested"><span>{t('pricingIntel.suggested')}</span><strong><bdi>{money(pricing.suggested)}</bdi></strong></div></div><div className="lp-recommendation"><span className="is-active"><Check size={14} />{t('pricingIntel.lower')}</span><span>{t('pricingIntel.hold')}</span><span>{t('pricingIntel.raise')}</span></div><div className="lp-market-range"><i /><i /><i /></div><div className="lp-three-stats">{[['min', pricing.min], ['avg', pricing.average], ['max', pricing.max]].map(([key, value]) => <div key={key}><span>{t(`pricingIntel.${key}`)}</span><b><bdi>{money(value)}</bdi></b></div>)}</div><dl className="lp-detail-list"><div><dt>{t('pricingIntel.matched')}</dt><dd>{n(pricing.matched)}</dd></div><div><dt>{t('pricingIntel.confidence')}</dt><dd>{percent(pricing.confidence)}</dd></div><div><dt>{t('pricingIntel.competitiveness')}</dt><dd><bdi>{n(pricing.score)} / {n(10)}</bdi></dd></div></dl><DemoCaption /></figure>;
}

export function SentimentVisual() {
  const { t, n, percent } = useLanding();
  return <figure className="lp-visual lp-sentiment-visual"><div className="lp-sentiment-main"><div className="lp-perception"><div className="lp-perception-ring"><strong>{n(demo.sentiment.perception)}<small>/ {n(100)}</small></strong></div><b>{t('sentiment.perception')}</b></div><div className="lp-sentiment-breakdown"><p>{t('sentiment.scope')}</p><div className="lp-sentiment-bar" aria-hidden="true">{['positive', 'neutral', 'negative'].map((key) => <span className={`lp-sentiment-${key}`} key={key} style={{ flex: demo.sentiment[key] }} />)}</div><div className="lp-sentiment-labels">{['positive', 'neutral', 'negative'].map((key) => <div key={key}><span><i className={`lp-sentiment-${key}`} />{t(`sentiment.${key}`)}</span><strong>{percent(demo.sentiment[key])}</strong></div>)}</div><div className="lp-sentiment-evidence"><span>{t('sentiment.reviews')}<b>{n(demo.sentiment.reviews)}</b></span><span>{t('sentiment.confidence')}<b>{percent(demo.sentiment.confidence)}</b></span></div></div><div className="lp-low-sample"><span className="lp-status lp-status--neutral">{t('sentiment.reliability')}</span><h3>{t('sentiment.limited')}</h3><p>{t('sentiment.limitedText')}</p></div></div><DemoCaption /></figure>;
}

export function RagVisual() {
  const { t, n } = useLanding();
  return <figure className="lp-visual lp-rag-visual"><VisualHeader title={t('rag.assistant')} /><div className="lp-chat-question">{t('rag.question')}</div><div className="lp-chat-answer"><span className="lp-icon"><Sparkles size={19} /></span><div><strong dir="ltr">CEOPRO AI</strong><p>{t('rag.answer')}</p><small>{t('common.source')}</small><div className="lp-sources">{demo.sources.map((source) => <div key={source.key}><FileText size={16} aria-hidden="true" /><span>{t(`rag.${source.key}`)}<small>{t('common.relevance')} · {n(source.relevance)}</small></span></div>)}</div></div></div><div className="lp-chat-placeholder"><span>{t('rag.placeholder')}</span><MessageCircle size={17} /></div><DemoCaption text={t('rag.note')} /></figure>;
}

export function ConnectionVisual() {
  const { t } = useLanding();
  const nodes = [{ key: 'analytics', Icon: BarChart3 }, { key: 'website', Icon: Globe2 }, { key: 'system', detail: 'systemDetail', Icon: Database }, { key: 'documents', detail: 'documentsDetail', Icon: FileSpreadsheet }];
  return <figure className="lp-connections"><div className="lp-connection-nodes">{nodes.map(({ key, Icon, detail }) => <div key={key} className="lp-connection-node"><span className="lp-icon"><Icon size={24} aria-hidden="true" /></span><strong>{t(`data.${key}`)}</strong>{detail && <small>{t(`data.${detail}`)}</small>}</div>)}</div><div className="lp-connection-stem" aria-hidden="true" /><div className="lp-connection-core"><Sparkles size={25} /><strong dir="ltr">CEOPRO AI</strong><span>{t('data.center')}</span></div></figure>;
}

export function IngestionVisual() {
  const { t, n, percent } = useLanding();
  return <figure className="lp-visual lp-ingestion-visual"><div className="lp-file-heading"><FileCheck2 size={30} /><div><strong>{t('ingestion.file')}</strong><span className="lp-status"><Check size={12} />{t('ingestion.compliance')}</span></div></div><div className="lp-three-stats">{['processed', 'partial', 'failed'].map((key) => <div key={key}><strong>{n(demo.extraction[key])}</strong><span>{t(`ingestion.${key}`)}</span></div>)}</div><dl className="lp-detail-list"><div><dt>{t('ingestion.headers')}</dt><dd>{percent(demo.extraction.headers)}</dd></div><div><dt>{t('ingestion.currency')}</dt><dd>{t('common.usd')}</dd></div></dl><DemoCaption /></figure>;
}

export function MiniVisual({ type }) {
  const { t, n } = useLanding();
  if (type === 'market') return <div className="lp-mini-market" aria-hidden="true">{[75, 91, 62].map((value, index) => <div key={value}><span>{t(`market.business${['A', 'B', 'C'][index]}`)}</span><i><b style={{ width: `${value}%` }} /></i><strong>{n(value)}</strong></div>)}</div>;
  if (type === 'demand') return <TrendChart compact forecast />;
  const Icons = { pricing: TrendingUp, sentiment: MessageCircle, rag: FileText, data: Database };
  const Icon = Icons[type] || ShoppingBag;
  return <div className={`lp-mini-symbol lp-mini-symbol--${type}`} aria-hidden="true"><span /><span /><Icon size={38} strokeWidth={1.4} /></div>;
}
