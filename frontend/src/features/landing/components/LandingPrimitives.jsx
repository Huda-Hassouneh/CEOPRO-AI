import { useEffect, useRef, useState } from 'react';
import { ArrowRight, Check, Sparkles } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import Button from '../../../shared/components/ui/Button.jsx';
import KeelMark from '../../../shared/components/brand/KeelMark.jsx';

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
  return <Link className="lp-brand" to={routePaths.landing} aria-label="KEEL"><span className="lp-brand-mark" aria-hidden="true"><KeelMark size={20} /></span><span className="lp-brand-word" dir="ltr">KEEL</span></Link>;
}

export function SectionHeading({ section, centered = false, children }) {
  const { t } = useLanding();
  return <div className={`lp-heading ${centered ? 'lp-heading--center' : ''}`}><p className="lp-eyebrow">{t(`${section}.eyebrow`)}</p><h2>{t(`${section}.title`)}</h2><p className="lp-description">{t(`${section}.description`)}</p>{children}</div>;
}

export function TrialButton({ children, className = '' }) {
  const { t } = useLanding();
  const navigate = useNavigate();
  const startTrial = () => {
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

const reducedMotion = () => typeof window === 'undefined' || !window.matchMedia
  || window.matchMedia('(prefers-reduced-motion: reduce)').matches;

// A figure that counts up from zero the first time it scrolls into view,
// shown through `format` (the page's own number/currency/percent formatter).
// Screen readers and reduced-motion visitors get the final value only.
export function CountUp({ value, format = String, duration = 1400 }) {
  const ref = useRef(null);
  const [shown, setShown] = useState(() => (reducedMotion() || typeof IntersectionObserver === 'undefined' ? value : 0));
  useEffect(() => {
    const el = ref.current;
    if (!el || reducedMotion() || typeof IntersectionObserver === 'undefined') { setShown(value); return undefined; }
    let frame = 0;
    const observer = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return;
      observer.disconnect();
      const start = performance.now();
      const step = (now) => {
        const progress = Math.min(1, (now - start) / duration);
        const eased = 1 - (1 - progress) ** 3;
        setShown(progress === 1 ? value : value * eased);
        if (progress < 1) frame = requestAnimationFrame(step);
      };
      frame = requestAnimationFrame(step);
    }, { threshold: 0.4 });
    observer.observe(el);
    return () => { observer.disconnect(); cancelAnimationFrame(frame); };
  }, [value, duration]);
  const decimals = Number.isInteger(value) ? 0 : 2;
  const current = shown === value ? value : Number(shown.toFixed(decimals));
  return <span ref={ref} className="lp-count"><span aria-hidden="true">{format(current)}</span><span className="lp-sr-only">{format(value)}</span></span>;
}
