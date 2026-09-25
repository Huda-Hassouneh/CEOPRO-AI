import { getUsageState } from "../utils/subscriptionRecommendations.js";

export function UsageLimitGrid({ usage, limits, features, locale, t }) {
  const number = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 });
  const keys = Object.keys(limits || {}).filter((key) => usage?.[key] != null);

  if (!keys.length)
    return (
      <p className="billing-usage-unavailable">
        {t("billing.management.usageUnavailable")}
      </p>
    );

  return (
    <div className="billing-usage-grid">
      {keys.map((key) => {
        const used = usage[key];
        const limit = limits[key];
        const state = getUsageState(used, limit);
        const percent =
          typeof limit === "number" && limit > 0
            ? Math.min(100, Math.max(0, (used / limit) * 100))
            : 0;
        const unit = key === "storageGb" ? t("billing.management.gb") : "";

        // 1. Extract dynamic label and fallback to existing translation keys if missing
        const featureData = features?.[key];
        const label =
          locale === "ar" && featureData?.name_ar
            ? featureData.name_ar
            : featureData?.name || t(`billing.management.usageLabels.${key}`);

        // 2. Extract dynamic description
        const description =
          locale === "ar" && featureData?.description_ar
            ? featureData.description_ar
            : featureData?.description;

        return (
          <article className={`billing-usage-card is-${state}`} key={key}>
            <header>
              <strong>{label}</strong>
              <span>{t(`billing.management.usageState.${state}`)}</span>
            </header>

            {/* Added the database description smoothly into your UI */}
            {description && (
              <div
                style={{
                  fontSize: "12px",
                  color: "var(--ceopro-text-muted)",
                  marginBottom: "8px"
                }}
              >
                {description}
              </div>
            )}

            <p>
              <bdi>
                {number.format(used)}
                {unit}
              </bdi>
              <small>
                /
                <bdi>
                  {limit === null ? "∞" : number.format(limit)}
                  {limit === null ? "" : unit}
                </bdi>
              </small>
            </p>

            {typeof limit === "number" && limit > 0 && (
              <div
                className="billing-usage-progress"
                role="progressbar"
                aria-label={label}
                aria-valuemin="0"
                aria-valuemax={limit}
                aria-valuenow={Math.min(used, limit)}
              >
                <span style={{ width: `${percent}%` }} />
              </div>
            )}
          </article>
        );
      })}
    </div>
  );
}
