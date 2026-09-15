import { BarChart3, BrainCircuit, ChartNoAxesCombined, Check, MessageCircle, TrendingUp } from 'lucide-react';
import { getPreviewPlan } from '../../billing/config/billingPreviewData.js';
import { FeatureLink, TrialButton, useLanding } from '../components/LandingPrimitives.jsx';
import { HeroVisual } from '../components/MarketingVisuals.jsx';

export function HeroSection() {
  const { t } = useLanding();
  const capabilities = [['market', BarChart3], ['demand', TrendingUp], ['pricing', ChartNoAxesCombined], ['sentiment', MessageCircle], ['rag', BrainCircuit]];
  return <><section id="hero" className="lp-hero"><div className="lp-container lp-hero-grid"><div className="lp-hero-copy"><span className="lp-badge"><span />{t('hero.badge')}</span><h1>{t('hero.title')}<span>{t('hero.accent')}</span></h1><p className="lp-description">{t('hero.description')}</p><div className="lp-actions"><TrialButton /><FeatureLink to="features" label={t('common.explore')} /></div><div className="lp-hero-notes"><span><Check size={14} />{t('hero.note', { days: getPreviewPlan('pro').trialDays })}</span><span><Check size={14} />{t('hero.bilingual')}</span></div></div><HeroVisual /></div></section><div className="lp-capability-strip"><div className="lp-container">{capabilities.map(([key, Icon]) => <a key={key} href={`#${key === 'pricing' ? 'pricing-intelligence' : key}`}><Icon size={20} aria-hidden="true" /><span>{t(`capabilities.${key}`)}</span></a>)}</div></div></>;
}
