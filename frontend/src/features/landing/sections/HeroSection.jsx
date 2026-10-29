import { BarChart3, BrainCircuit, ChartNoAxesCombined, Check, MessageCircle, TrendingUp } from 'lucide-react';
import { useTrialDays } from '../../billing/hooks/useTrialDays.js';
import { FeatureLink, TrialButton, useLanding } from '../components/LandingPrimitives.jsx';
import { HeroVisual } from '../components/MarketingVisuals.jsx';
import { HeroNetwork } from '../components/HeroNetwork.jsx';
import { SplineHero } from '../components/SplineHero.jsx';

export function HeroSection() {
  const { t } = useLanding();
  const trialDays = useTrialDays();
  const capabilities = [['market', BarChart3], ['demand', TrendingUp], ['pricing', ChartNoAxesCombined], ['sentiment', MessageCircle], ['rag', BrainCircuit]];
  return <><section id="hero" className="lp-hero"><HeroNetwork /><div className="lp-container lp-hero-grid"><div className="lp-hero-copy"><span className="lp-badge"><span />{t('hero.badge')}</span><h1>{t('hero.title')}<span>{t('hero.accent')}</span></h1><p className="lp-description">{t('hero.description')}</p><div className="lp-actions"><TrialButton /><FeatureLink to="try" label={t('common.tryLive')} /></div><div className="lp-hero-notes"><span><Check size={14} />{t('hero.note', { days: trialDays })}</span><span><Check size={14} />{t('hero.bilingual')}</span></div></div><SplineHero fallback={<HeroVisual />} label={t('hero.title')} /></div></section><div className="lp-capability-strip"><div className="lp-container">{capabilities.map(([key, Icon]) => <a key={key} href={`#${key === 'pricing' ? 'pricing-intelligence' : key}`}><Icon size={20} aria-hidden="true" /><span>{t(`capabilities.${key}`)}</span></a>)}</div></div></>;
}
