import { useI18n } from "../providers/I18nProvider.jsx";
import { AuthLanguageSwitch } from "../../features/auth/components/AuthLanguageSwitch.jsx";

export function AuthLayout({
  children,
  brand = false,
  brandLabel,
  wide = false,
  className = ""
}) {
  const { dir, t } = useI18n();
  const resolvedBrandLabel = brandLabel || t("common.brand");

  return (
    <div className="ceopro-auth-page" dir={dir}>
      <div
        className="ceopro-auth-shape ceopro-auth-shape--one"
        aria-hidden="true"
      />
      <div
        className="ceopro-auth-shape ceopro-auth-shape--two"
        aria-hidden="true"
      />
      <div
        className="ceopro-auth-shape ceopro-auth-shape--three"
        aria-hidden="true"
      />
      {brand && <AuthLanguageSwitch />}

      <div
        className={`ceopro-auth-wrapper ${wide ? "ceopro-auth-wrapper--wide" : ""} ${className}`.trim()}
      >
        {brand && (
          <div className="ceopro-auth-brand" aria-label={resolvedBrandLabel}>
            {resolvedBrandLabel}
          </div>
        )}

        <section className="ceopro-auth-shell">
          <div className="ceopro-auth-topbar" aria-hidden="true" />
          {children}
        </section>
      </div>
    </div>
  );
}
