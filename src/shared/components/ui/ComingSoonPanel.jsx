import { Sparkles } from "lucide-react";

export function ComingSoonPanel({ t, title, subtitle }) {
  return (
    <section className="ceopro-card ceopro-coming-soon-panel">
      {/* Header aligned with system typography variables */}
      <div className="ceopro-coming-soon-header">
        <h2>{title}</h2>
        {subtitle && <p>{subtitle}</p>}
      </div>

      {/* Dashed placeholder container */}
      <div className="ceopro-coming-soon-content">
        <div className="ceopro-coming-soon-icon">
          <Sparkles size={30} strokeWidth={1.5} />
        </div>

        <h3>{t("common.comingSoon", "Coming Soon")}</h3>

        <p>
          {t(
            "common.comingSoonDescription",
            "We are building something extraordinary. Advanced analytics and deeper market insights are currently in development to elevate your strategy."
          )}
        </p>
      </div>
    </section>
  );
}
