import { useEffect, useRef, useState } from 'react';
import { BarChart3, Boxes, Lightbulb, MessageCircle, Package, RotateCcw, ShoppingCart, Sparkles, Star, Tags, TrendingDown, Truck } from 'lucide-react';
import { DemoCaption, TrialButton, useLanding } from '../components/LandingPrimitives.jsx';

// "Try it now": a visitor picks a question an owner asks every week and
// watches KEEL answer it - typed out, then the evidence behind it, then a
// next step - before being asked to sign up. Scripted, illustrative answers
// (labelled as such); no request leaves the page. The first question plays
// by itself when the section scrolls into view.
const QUESTIONS = [
  { key: '1', evidence: [ShoppingCart, Boxes, Truck], sources: ['sales', 'inventory'] },
  { key: '2', evidence: [Tags, TrendingDown, Package], sources: ['competitors', 'sales'] },
  { key: '3', evidence: [Star, MessageCircle, Truck], sources: ['reviews'] },
];
// The data a real answer draws on; the ones this question reads light up while KEEL "thinks".
const SOURCES = [['sales', BarChart3], ['inventory', Boxes], ['competitors', Tags], ['reviews', Star]];
const THINKING_MS = 1100;
const TYPING_MS = 16;

const reducedMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

export function TryItSection() {
  const { t } = useLanding();
  const [active, setActive] = useState(null);
  const [phase, setPhase] = useState('idle'); // idle | thinking | typing | done
  const [typed, setTyped] = useState(0);
  const sectionRef = useRef(null);
  const answer = active ? t(`tryIt.a${active}`) : '';

  const started = useRef(false);
  const ask = (key) => {
    started.current = true;
    setActive(key);
    setTyped(0);
    setPhase(reducedMotion() ? 'done' : 'thinking');
  };

  // Play the first question once, when the section first comes into view.
  useEffect(() => {
    const el = sectionRef.current;
    if (!el || typeof IntersectionObserver === 'undefined') { ask('1'); return undefined; }
    const observer = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return;
      observer.disconnect();
      if (!started.current) ask('1');
    }, { threshold: 0.35 });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (phase === 'thinking') {
      const timer = setTimeout(() => setPhase('typing'), THINKING_MS);
      return () => clearTimeout(timer);
    }
    if (phase === 'typing') {
      if (typed >= answer.length) { setPhase('done'); return undefined; }
      const timer = setTimeout(() => setTyped((n) => Math.min(answer.length, n + 2)), TYPING_MS);
      return () => clearTimeout(timer);
    }
    return undefined;
  }, [phase, typed, answer]);

  const question = QUESTIONS.find((q) => q.key === active);
  const shown = phase === 'done' ? answer : answer.slice(0, typed);

  return <section className="lp-section lp-try" id="try" ref={sectionRef}>
    <div className="lp-container">
      <div className="lp-heading lp-heading--center"><p className="lp-eyebrow">{t('tryIt.eyebrow')}</p><h2>{t('tryIt.title')}</h2><p className="lp-description">{t('tryIt.description')}</p></div>
      <div className="lp-try-layout">
        <div className="lp-try-questions" role="group" aria-label={t('tryIt.pick')}>
          <p className="lp-try-pick">{t('tryIt.pick')}</p>
          {QUESTIONS.map(({ key }) => <button type="button" key={key} className={`lp-try-chip${active === key ? ' is-active' : ''}`} aria-pressed={active === key} onClick={() => ask(key)}>
            <MessageCircle size={17} aria-hidden="true" /><span>{t(`tryIt.q${key}`)}</span>
          </button>)}
          <div className="lp-try-sources">
            <p>{t('tryIt.sourcesText')}</p>
            <ul>{SOURCES.map(([key, Icon]) => <li key={key} className={phase === 'thinking' && question?.sources.includes(key) ? 'is-live' : ''}><Icon size={14} aria-hidden="true" />{t(`tryIt.source_${key}`)}</li>)}</ul>
          </div>
        </div>
        <figure className="lp-visual lp-try-chat" aria-busy={phase === 'thinking' || phase === 'typing'}>
          <div className="lp-try-window" aria-hidden="true"><i /><i /><i /><span dir="ltr">KEEL</span></div>
          {question && <>
            <div className="lp-chat-question lp-try-in" key={`q${active}`}>{t(`tryIt.q${active}`)}</div>
            <div className="lp-try-answer">
              <span className="lp-icon"><Sparkles size={19} aria-hidden="true" /></span>
              <div>
                <strong dir="ltr">KEEL</strong>
                {phase === 'thinking'
                  ? <p className="lp-try-thinking"><span className="lp-try-dots" aria-hidden="true"><i /><i /><i /></span>{t('tryIt.thinking')}</p>
                  : <p><span aria-hidden="true">{shown}{phase === 'typing' && <span className="lp-try-caret" />}</span><span className="lp-sr-only">{answer}</span></p>}
                {phase === 'done' && <div className="lp-try-details" key={`d${active}`}>
                  <small>{t('tryIt.evidence')}</small>
                  <ul className="lp-try-evidence">{question.evidence.map((Icon, index) => <li key={index}><Icon size={16} aria-hidden="true" /><span>{t(`tryIt.e${active}${'abc'[index]}`)}</span></li>)}</ul>
                  <div className="lp-try-action"><Lightbulb size={18} aria-hidden="true" /><div><small>{t('tryIt.action')}</small><b>{t(`tryIt.act${active}`)}</b></div></div>
                </div>}
              </div>
            </div>
          </>}
          <DemoCaption />
        </figure>
      </div>
      <div className={`lp-try-cta${phase === 'done' ? ' is-ready' : ''}`}>
        <div><h3>{t('tryIt.ctaTitle')}</h3><p>{t('tryIt.ctaText')}</p></div>
        <div className="lp-try-cta-actions">
          <TrialButton />
          {phase === 'done' && <button type="button" className="lp-text-link lp-try-replay" onClick={() => ask(QUESTIONS[(QUESTIONS.findIndex((q) => q.key === active) + 1) % QUESTIONS.length].key)}><RotateCcw size={15} aria-hidden="true" />{t('tryIt.replay')}</button>}
        </div>
      </div>
    </div>
  </section>;
}
