import { BarChart3, Boxes, BrainCircuit, Check, CircleHelp, Compass, Database, FileSearch, Fingerprint, Globe2, Layers3, MessageCircle, ScanLine, Sparkles, Tags, Target, TrendingUp } from 'lucide-react';
import { Link } from 'react-router-dom';
import { routePaths } from '../../../app/router/routePaths.js';
import { getPreviewPlan } from '../../billing/config/billingPreviewData.js';
import { SectionHeading, TrialButton, useLanding } from '../components/LandingPrimitives.jsx';

const models = [['pricing', Tags, 'pricing-intelligence'], ['sentiment', MessageCircle, 'sentiment'], ['perception', Fingerprint, 'sentiment'], ['demand', TrendingUp, 'demand'], ['market', BarChart3, 'market'], ['rag', BrainCircuit, 'rag'], ['extraction', ScanLine, 'file-intelligence']];
export function ModelsSection() {
  const { t } = useLanding();
  return <section className="lp-section lp-models-section" id="models"><div className="lp-container"><SectionHeading section="models" centered /><div className="lp-models-grid"><div className="lp-model-core"><div className="lp-model-orbit" aria-hidden="true"><span /><BrainCircuit size={58} strokeWidth={1} /></div><h3 dir="ltr">{t('models.core')}</h3><p>{t('models.coreText')}</p></div><div className="lp-model-list">{models.map(([key, Icon, target], index) => <a className="lp-model" key={key} href={`#${target}`}><span className="lp-icon"><Icon size={22} aria-hidden="true" /></span><div><h3>{t(`models.${key}`)}</h3><p>{t(`models.${key}Text`)}</p></div><span className="lp-model-number" aria-hidden="true">0{index + 1}</span></a>)}</div></div></div></section>;
}

export function WorkflowSection() {
  const { t, n } = useLanding();
  return <section className="lp-section" id="how-it-works"><div className="lp-container"><div className="lp-heading lp-heading--center"><p className="lp-eyebrow">{t('workflow.eyebrow')}</p><h2>{t('workflow.title')}</h2></div><ol className="lp-workflow">{[['connect', Database], ['analyze', Sparkles], ['understand', Compass], ['act', Target]].map(([key, Icon], index) => <li key={key}><div className="lp-workflow-icon"><Icon size={27} aria-hidden="true" /><span>{n(index + 1)}</span></div><h3>{t(`workflow.${key}`)}</h3><p>{t(`workflow.${key}Text`)}</p></li>)}</ol></div></section>;
}

export function OutcomesSection() {
  const { t } = useLanding();
  return <section className="lp-section lp-tinted" id="outcomes"><div className="lp-container lp-outcomes-layout"><div className="lp-heading"><p className="lp-eyebrow">{t('outcomes.eyebrow')}</p><h2>{t('outcomes.title')}</h2><div className="lp-outcome-art" aria-hidden="true"><div /><Target size={92} strokeWidth={.8} /><span><Check size={24} /></span></div></div><div className="lp-outcomes-list">{[['market', Compass], ['inventory', Boxes], ['pricing', Tags], ['customers', MessageCircle], ['answers', FileSearch], ['evidence', Layers3]].map(([key, Icon]) => <div key={key}><Icon size={23} aria-hidden="true" /><div><h3>{t(`outcomes.${key}`)}</h3><p>{t(`outcomes.${key}Text`)}</p></div></div>)}</div></div></section>;
}

export function AboutSection() {
  const { t } = useLanding();
  return <section className="lp-section" id="about"><div className="lp-container lp-split"><SectionHeading section="about" /><div className="lp-about-visual"><div className="lp-about-inputs">{[['internal', Database], ['external', Globe2]].map(([key, Icon]) => <div key={key}><Icon size={27} aria-hidden="true" /><h3>{t(`about.${key}`)}</h3><p>{t(`about.${key}Text`)}</p></div>)}</div><div className="lp-about-result"><Sparkles size={21} /><strong>{t('about.together')}</strong></div><div className="lp-about-points">{['bilingual', 'evidence'].map((key) => <div key={key}><Check size={18} /><div><h3>{t(`about.${key}`)}</h3><p>{t(`about.${key}Text`)}</p></div></div>)}</div></div></div></section>;
}

export function TrustSection() {
  const { t } = useLanding();
  return <section className="lp-section lp-trust-section" id="trust"><div className="lp-container"><div className="lp-heading lp-heading--center"><p className="lp-eyebrow">{t('trust.eyebrow')}</p><h2>{t('trust.title')}</h2></div><div className="lp-trust-grid">{[['sources', FileSearch], ['uncertainty', CircleHelp], ['control', Target]].map(([key, Icon]) => <div key={key}><Icon size={28} strokeWidth={1.4} aria-hidden="true" /><h3>{t(`trust.${key}`)}</h3><p>{t(`trust.${key}Text`)}</p></div>)}</div></div></section>;
}

export function FinalCtaSection() {
  const { t } = useLanding();
  return <section className="lp-final-cta"><div className="lp-container"><div className="lp-cta-orbit" aria-hidden="true" /><p className="lp-eyebrow">{t('cta.eyebrow')}</p><h2>{t('cta.title')}</h2><p>{t('cta.description', { days: getPreviewPlan('pro').trialDays })}</p><div className="lp-actions"><TrialButton /><Link to={routePaths.login}>{t('nav.login')}</Link></div></div></section>;
}
