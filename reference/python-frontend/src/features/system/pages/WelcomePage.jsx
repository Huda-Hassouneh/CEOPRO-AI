import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, BrainCircuit, ChartNoAxesCombined, LogIn, Radar, TrendingUp } from 'lucide-react';
import { routePaths } from '../../../app/router/routePaths.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import KeelMark from '../../../shared/components/brand/KeelMark.jsx';
import { AuthLanguageSwitch } from '../../auth/components/AuthLanguageSwitch.jsx';
import { InsightOrb } from '../components/InsightOrb.jsx';
import './WelcomePage.css';

// Capabilities KEEL ships today (market discovery, demand forecasting,
// pricing recommendations, the assistant) - high level only.
const INSIGHTS = [
  { key: 'market', Icon: Radar },
  { key: 'demand', Icon: TrendingUp },
  { key: 'pricing', Icon: ChartNoAxesCombined },
  { key: 'ai', Icon: BrainCircuit },
];

const REDUCED_MOTION = '(prefers-reduced-motion: reduce)';

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(() => typeof window !== 'undefined' && window.matchMedia?.(REDUCED_MOTION).matches);
  useEffect(() => {
    const query = window.matchMedia?.(REDUCED_MOTION);
    if (!query) return undefined;
    const update = () => setReduced(query.matches);
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  return reduced;
}

export default function WelcomePage() {
  const { dir, t } = useI18n();
  const reducedMotion = usePrefersReducedMotion();
  const rootRef = useRef(null);

  // Cursor-responsive light and parallax: the pointer position is written to
  // CSS variables once per frame - no React state, so no re-renders. Only for
  // a fine pointer and when motion is allowed.
  useEffect(() => {
    const root = rootRef.current;
    if (!root || reducedMotion || !window.matchMedia?.('(pointer: fine)').matches) return undefined;
    let frame = 0;
    let x = 0.5;
    let y = 0.4;
    const apply = () => {
      frame = 0;
      root.style.setProperty('--kw-mx', x.toFixed(4));
      root.style.setProperty('--kw-my', y.toFixed(4));
    };
    const onMove = (event) => {
      x = event.clientX / window.innerWidth;
      y = event.clientY / window.innerHeight;
      if (!frame) frame = window.requestAnimationFrame(apply);
    };
    window.addEventListener('pointermove', onMove, { passive: true });
    return () => {
      window.removeEventListener('pointermove', onMove);
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, [reducedMotion]);

  // Log In / Get Started cross-fade into the auth screens with the View
  // Transitions API where the browser has it (react-router's viewTransition);
  // the attribute scopes the animation to this hand-off only.
  const markTransition = () => {
    if (reducedMotion) return;
    const html = document.documentElement;
    html.dataset.keelTransition = 'welcome';
    window.setTimeout(() => { delete html.dataset.keelTransition; }, 1200);
  };

  return (
    <div className="kw" dir={dir} ref={rootRef}>
      <div className="kw-atmosphere" aria-hidden="true">
        <div className="kw-aurora kw-aurora--violet" />
        <div className="kw-aurora kw-aurora--cyan" />
        <div className="kw-aurora kw-aurora--indigo" />
        <div className="kw-beam" />
        <div className="kw-grid" />
        <div className="kw-cursor-light" />
        <div className="kw-grain" />
      </div>

      <header className="kw-top">
        <Link className="kw-brand" to={routePaths.landing} aria-label={t('common.brand')}>
          <span className="kw-brand-mark"><KeelMark size={22} variant="plain" /></span>
          <span className="kw-brand-word" dir="ltr">KEEL</span>
        </Link>
        <AuthLanguageSwitch />
      </header>

      <main className="kw-main">
        <section className="kw-copy" aria-labelledby="welcome-heading">
          <p className="kw-eyebrow kw-enter" style={{ '--kw-delay': '80ms' }}>
            <span className="kw-eyebrow-dot" aria-hidden="true" />{t('auth.welcome.eyebrow')}
          </p>
          <h1 id="welcome-heading" className="kw-title kw-enter" style={{ '--kw-delay': '180ms' }}>
            {t('auth.welcome.title')} <span className="kw-title-accent">{t('auth.welcome.titleAccent')}</span>
          </h1>
          <p className="kw-lead kw-enter" style={{ '--kw-delay': '300ms' }}>{t('auth.welcome.tagline')}</p>
          <p className="kw-description kw-enter" style={{ '--kw-delay': '380ms' }}>{t('auth.welcome.description')}</p>

          <div className="kw-actions kw-enter" style={{ '--kw-delay': '480ms' }}>
            <Link className="kw-button kw-button--primary" to={routePaths.signup} viewTransition onClick={markTransition}>
              <span>{t('auth.welcome.getStarted')}</span>
              <ArrowRight className="kw-button-arrow" size={18} aria-hidden="true" />
            </Link>
            <Link className="kw-button kw-button--glass" to={routePaths.login} viewTransition onClick={markTransition}>
              <LogIn className="kw-button-icon" size={17} aria-hidden="true" />
              <span>{t('auth.welcome.login')}</span>
            </Link>
          </div>
          <p className="kw-note kw-enter" style={{ '--kw-delay': '560ms' }}>{t('auth.welcome.note')}</p>
        </section>

        <section className="kw-stage" aria-label={t('auth.welcome.insightsLabel')}>
          <div className="kw-stage-visual kw-enter kw-enter--scale" style={{ '--kw-delay': '260ms' }}>
            <InsightOrb animate={!reducedMotion} />
          </div>
          <ul className="kw-insights">
            {INSIGHTS.map(({ key, Icon }, index) => (
              <li key={key} className={`kw-insight-slot kw-insight-slot--${key} kw-enter`} style={{ '--kw-delay': `${640 + index * 120}ms` }}>
                <div className="kw-insight kw-glass" style={{ '--kw-float': `${index * -1.7}s` }}>
                  <span className="kw-insight-icon" aria-hidden="true"><Icon size={18} /></span>
                  <span className="kw-insight-text">
                    <strong>{t(`auth.welcome.insights.${key}.title`)}</strong>
                    <span>{t(`auth.welcome.insights.${key}.text`)}</span>
                  </span>
                </div>
              </li>
            ))}
          </ul>
        </section>
      </main>
    </div>
  );
}
