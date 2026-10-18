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
  OutcomesSection,
  TrustSection,
  WorkflowSection,
} from "../sections/ValueSections.jsx";
import { PricingSection } from "../sections/PricingSection.jsx";
import "../styles/Landing.css";

export default function LandingPage() {
  const { t, locale } = useLanding();
  useEffect(() => {
    const originalTitle = document.title;
    const existingDescription = document.querySelector(
      'meta[name="description"]',
    );
    const originalDescription = existingDescription?.content;
    const description = existingDescription || document.createElement("meta");
    description.name = "description";
    description.content = t("meta.description");
    if (!existingDescription) document.head.appendChild(description);
    document.title = t("meta.title");
    return () => {
      document.title = originalTitle;
      if (existingDescription) description.content = originalDescription;
      else description.remove();
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
        <OutcomesSection />
        <AboutSection />
        <PricingSection />
        <TrustSection />
        <FinalCtaSection />
      </main>
      <LandingFooter />
    </div>
  );
}
