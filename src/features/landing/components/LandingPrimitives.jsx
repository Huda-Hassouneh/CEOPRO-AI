import { ArrowRight, Check, Sparkles } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import Button from '../../../shared/components/ui/Button.jsx';
import { useOnboardingStore } from '../../onboarding/store/onboardingStore.js';

export function useLanding() {
  const { t, locale, ...rest } = useI18n();
  const language = locale === 'ar' ? 'ar-JO' : 'en-US';
  return {
    ...rest, locale, t: (key, values) => t(`landing.${key}`, values),
    n: (value) => new Intl.NumberFormat(language, { maximumFractionDigits: 2 }).format(value),
    percent: (value) => new Intl.NumberFormat(language, { style: 'percent', maximumFractionDigits: 1 }).format(value / 100),
    money: (value) => new Intl.NumberFormat(language, { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(value),
  };
}

export function Brand() {
  return <Link className="lp-brand" to={routePaths.landing} aria-label="CEOPRO AI"><span className="lp-brand-symbol" aria-hidden="true"><i /><i /><i /></span><span dir="ltr">CEO<span>PRO</span><small>AI</small></span></Link>;
}

export function SectionHeading({ section, centered = false, children }) {
  const { t } = useLanding();
  return <div className={`lp-heading ${centered ? 'lp-heading--center' : ''}`}><p className="lp-eyebrow">{t(`${section}.eyebrow`)}</p><h2>{t(`${section}.title`)}</h2><p className="lp-description">{t(`${section}.description`)}</p>{children}</div>;
}

export function TrialButton({ children, className = '' }) {
  const { t } = useLanding();
  const navigate = useNavigate();
  const setPlanChoice = useOnboardingStore((state) => state.setPlanChoice);
  const startTrial = () => {
    setPlanChoice('pro', 'trial');
    navigate(routePaths.welcome);
  };
  return <Button size="lg" className={className} onClick={startTrial} trailingIcon={<ArrowRight className="lp-arrow" size={18} aria-hidden="true" />}>{children || t('common.trial')}</Button>;
}

export function DemoCaption({ text }) {
  const { t } = useLanding();
  return <figcaption className="lp-demo-caption"><span aria-hidden="true" />{text || t('common.demo')}</figcaption>;
}

export function VisualHeader({ title, subtitle }) {
  return <div className="lp-visual-header"><div><strong>{title}</strong>{subtitle && <small>{subtitle}</small>}</div><Sparkles size={18} aria-hidden="true" /></div>;
}

export function PointList({ section, count = 3 }) {
  const { t } = useLanding();
  return <ul className="lp-points">{Array.from({ length: count }, (_, i) => <li key={i}><Check size={17} aria-hidden="true" />{t(`${section}.point${i + 1}`)}</li>)}</ul>;
}

export function FeatureLink({ to, label }) {
  const { t } = useLanding();
  return <a className="lp-text-link" href={`#${to}`}>{label || t('common.learn')}<ArrowRight size={16} className="lp-arrow" aria-hidden="true" /></a>;
}
