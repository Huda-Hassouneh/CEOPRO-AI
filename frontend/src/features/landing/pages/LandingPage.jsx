import { useEffect, useRef } from 'react';
import { LandingFooter, LandingNavbar } from '../components/LandingNavigation.jsx';
import { useLanding } from '../components/LandingPrimitives.jsx';
import { HeroSection } from '../sections/HeroSection.jsx';
import { FeaturesSection } from '../sections/FeaturesSection.jsx';
import { IntelligenceSections } from '../sections/IntelligenceSections.jsx';
import { KnowledgeSections } from '../sections/KnowledgeSections.jsx';
import { AboutSection, FinalCtaSection, ModelsSection, OutcomesSection, TrustSection, WorkflowSection } from '../sections/ValueSections.jsx';
import { PricingSection } from '../sections/PricingSection.jsx';
import '../styles/Landing.css';

export default function LandingPage() {
  const { t, locale } = useLanding();
  useEffect(() => {
    const originalTitle = document.title;
    const existingDescription = document.querySelector('meta[name="description"]');
    const originalDescription = existingDescription?.content;
    const description = existingDescription || document.createElement('meta');
    description.name = 'description';
    description.content = t('meta.description');
    if (!existingDescription) document.head.appendChild(description);
    document.title = t('meta.title');
    return () => {
      document.title = originalTitle;
      if (existingDescription) description.content = originalDescription;
      else description.remove();
    };
  }, [locale, t]); // The existing provider is the sole locale/direction owner.

  // Sections glide into view as they are scrolled to (content stays visible
  // without JS or with reduced motion: the hidden state needs .lp-motion).
  const rootRef = useRef(null);
  useEffect(() => {
    const root = rootRef.current;
    if (!root || typeof IntersectionObserver === 'undefined' || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return undefined;
    root.classList.add('lp-motion');
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => { if (entry.isIntersecting) { entry.target.classList.add('is-visible'); observer.unobserve(entry.target); } });
    }, { rootMargin: '0px 0px -12% 0px', threshold: 0.08 });
    root.querySelectorAll('main > section:not(#hero), main > div:not(.lp-capability-strip)').forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, []);

  const scrollToSection = (event) => {
    const anchor = event.target.closest('a[href^="#"]');
    if (!anchor || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const target = document.getElementById(anchor.hash.slice(1));
    if (!target) return;
    event.preventDefault();
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    window.history.replaceState(window.history.state, '', anchor.hash);
    target.scrollIntoView({ behavior: reduceMotion ? 'instant' : 'smooth', block: 'start' });
    // Move keyboard context with the anchor, without altering sequential tab order.
    target.setAttribute('tabindex', '-1');
    target.focus({ preventScroll: true });
  };

  return <div className="ceopro-landing" ref={rootRef} onClick={scrollToSection}>
    <a className="lp-skip-link" href="#landing-main">{t('nav.skip')}</a>
    <LandingNavbar />
    <main id="landing-main"><HeroSection /><FeaturesSection /><IntelligenceSections /><KnowledgeSections /><ModelsSection /><WorkflowSection /><OutcomesSection /><AboutSection /><PricingSection /><TrustSection /><FinalCtaSection /></main>
    <LandingFooter />
  </div>;
}
