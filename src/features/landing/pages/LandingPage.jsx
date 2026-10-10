import { useEffect } from "react";
import {
  LandingFooter,
  LandingNavbar,
} from "../components/LandingNavigation.jsx";
import { useLanding } from "../components/LandingPrimitives.jsx";
import { HeroSection } from "../sections/HeroSection.jsx";
import { FeaturesSection } from "../sections/FeaturesSection.jsx";
import { IntelligenceSections } from "../sections/IntelligenceSections.jsx";
import { KnowledgeSections } from "../sections/KnowledgeSections.jsx";
import {
  AboutSection,
  FinalCtaSection,
  ModelsSection,
  TrustSection,
  WorkflowSection,
} from "../sections/ValueSections.jsx";
import { PricingSection } from "../sections/PricingSection.jsx";
import "../styles/Landing.css";

export default function LandingPage() {
  const { t, locale } = useLanding();
  useEffect(() => {
    const originalTitle = document.title;
    const tags = [
      ['name', 'description', t('meta.description')],
      ['property', 'og:title', t('meta.title')],
      ['property', 'og:description', t('meta.description')],
      ['property', 'og:type', 'website'],
      ['property', 'og:site_name', 'KEEL'],
      ['property', 'og:locale', locale === 'ar' ? 'ar_JO' : 'en_US'],
      ['name', 'twitter:card', 'summary'],
      ['name', 'twitter:title', t('meta.title')],
      ['name', 'twitter:description', t('meta.description')],
    ];
    const restore = tags.map(([attribute, key, content]) => {
      const existing = document.querySelector(`meta[${attribute}="${key}"]`);
      const element = existing || document.createElement('meta');
      const original = existing?.getAttribute('content');
      element.setAttribute(attribute, key);
      element.setAttribute('content', content);
      if (!existing) document.head.appendChild(element);
      return () => {
        if (!existing) element.remove();
        else if (original === null) element.removeAttribute('content');
        else element.setAttribute('content', original);
      };
    });
    document.title = t("meta.title");
    return () => {
      document.title = originalTitle;
      restore.forEach((restoreTag) => restoreTag());
    };
  }, [locale]); // The existing provider is the sole locale/direction owner.

  const scrollToSection = (event) => {
    const anchor = event.target.closest('a[href^="#"]');
    if (
      !anchor ||
      event.ctrlKey ||
      event.metaKey ||
      event.shiftKey ||
      event.altKey
    )
      return;
    const target = document.getElementById(anchor.hash.slice(1));
    if (!target) return;
    event.preventDefault();
    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    window.history.replaceState(window.history.state, "", anchor.hash);
    target.scrollIntoView({
      behavior: reduceMotion ? "instant" : "smooth",
      block: "start",
    });
    // Move keyboard context with the anchor, without altering sequential tab order.
    target.setAttribute("tabindex", "-1");
    target.focus({ preventScroll: true });
  };

  return (
    <div className="ceopro-landing" onClick={scrollToSection}>
      <a className="lp-skip-link" href="#landing-main">
        {t("nav.skip")}
      </a>
      <LandingNavbar />
      <main id="landing-main">
        <HeroSection />
        <FeaturesSection />
        <IntelligenceSections />
        <KnowledgeSections />
        <ModelsSection />
        <WorkflowSection />
        <AboutSection />
        <PricingSection />
        <TrustSection />
        <FinalCtaSection />
      </main>
      <LandingFooter />
    </div>
  );
}
