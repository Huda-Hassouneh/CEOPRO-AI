import { Check } from "lucide-react";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";

export function PlanComparisonTable({ plans, currentPlanId }) {
  const { locale, t } = useI18n();
  // Ensure the number formatter uses the correct locale styling
  const number = new Intl.NumberFormat(locale === "ar" ? "ar-JO" : "en-US");

  const featureKeys = [
    ...new Set(plans.flatMap((plan) => Object.keys(plan.features || {})))
  ];

  if (!plans.length || !featureKeys.length) return null;

  return (
    <div className="billing-comparison-wrap">
      <table className="billing-comparison-table">
        <thead>
          <tr>
            <th>{t("billing.management.comparison.limit")}</th>
            {plans.map((plan) => {
              // 1. Grab the localized plan name
              const finalPlanName = plan.displayName || plan.name || "";
              return (
                <th key={plan.id}>
                  {finalPlanName
                    ? finalPlanName.charAt(0).toUpperCase() +
                      finalPlanName.slice(1)
                    : ""}
                  {currentPlanId === plan.id && (
                    <span>
                      <Check size={11} />
                      {t("billing.management.currentPlan")}
                    </span>
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {featureKeys.map((key) => {
            // Find the first plan that has this feature to extract its metadata
            const sampleFeature = plans.find((plan) => plan.features?.[key])
              ?.features[key];

            // 2. Extract Arabic or English Feature Name
            const featureName =
              locale === "ar" && sampleFeature?.name_ar
                ? sampleFeature.name_ar
                : sampleFeature?.name ||
                  t(`billing.management.usageLabels.${key}`);

            // 3. Extract Arabic or English Feature Description
            const featureDesc =
              locale === "ar" && sampleFeature?.description_ar
                ? sampleFeature.description_ar
                : sampleFeature?.description;

            return (
              <tr key={key}>
                <th>
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: "2px"
                    }}
                  >
                    <span>{featureName}</span>
                    {/* Add the database description smoothly into the table UI */}
                    {featureDesc && (
                      <span
                        style={{
                          fontSize: "12px",
                          color: "var(--ceopro-text-muted)",
                          fontWeight: "normal"
                        }}
                      >
                        {featureDesc}
                      </span>
                    )}
                  </div>
                </th>
                {plans.map((plan) => {
                  if (plan.isCustomBuilder) {
                    const customValue =
                      sampleFeature?.type === "boolean"
                        ? locale === "ar"
                          ? "اختياري"
                          : "Optional"
                        : locale === "ar"
                          ? "قابل للتخصيص"
                          : "Configurable";

                    return (
                      <td key={plan.id}>
                        <strong>{customValue}</strong>
                      </td>
                    );
                  }

                  const feature = plan.features?.[key];
                  return (
                    <td key={plan.id}>
                      {feature?.limitValue === null ? (
                        "∞"
                      ) : feature?.limitValue === undefined ? (
                        "--"
                      ) : (
                        <bdi>
                          {number.format(feature.limitValue)}
                          {(
                            locale === "ar"
                              ? feature.unit_ar || feature.unit
                              : feature.unit
                          )
                            ? ` ${locale === "ar" ? feature.unit_ar || feature.unit : feature.unit}`
                            : ""}
                        </bdi>
                      )}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
