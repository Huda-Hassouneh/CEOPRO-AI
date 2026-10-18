import { LANDING_DEMO } from '../data/demoData.js';
import { DemoCaption, PointList, SectionHeading, useLanding } from '../components/LandingPrimitives.jsx';
import { DemandVisual, MarketVisual, PricingVisual, SentimentVisual } from '../components/MarketingVisuals.jsx';

export function IntelligenceSections() {
  const { t, n } = useLanding();
  return <>
    <section className="lp-section lp-tinted" id="market"><div className="lp-container lp-split lp-split--market"><SectionHeading section="market"><PointList section="market" /></SectionHeading><MarketVisual /></div></section>
    <section className="lp-section" id="demand"><div className="lp-container lp-split lp-split--reverse"><DemandVisual /><SectionHeading section="demand"><p className="lp-fineprint">{t('demand.note')}</p></SectionHeading></div></section>
    <section className="lp-section lp-tinted" id="pricing-intelligence"><div className="lp-container lp-split"><SectionHeading section="pricingIntel"><p className="lp-fineprint">{t('pricingIntel.note')}</p></SectionHeading><PricingVisual /></div></section>
    <section className="lp-section" id="sentiment"><div className="lp-container"><SectionHeading section="sentiment" centered /><SentimentVisual /></div></section>
    <section className="lp-score-section" id="scores"><div className="lp-container lp-score-layout"><SectionHeading section="scoring" /><figure className="lp-score-figure"><div className="lp-scores">{LANDING_DEMO.scores.map(({ key, value, max }) => <div key={key}><span>{t(`scoring.${key}`)}</span><strong>{n(value)}<small> / {n(max)}</small></strong><div className="lp-score-track"><i style={{ width: `${value / max * 100}%` }} /></div></div>)}</div><DemoCaption /></figure></div></section>
  </>;
}
