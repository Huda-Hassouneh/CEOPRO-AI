import { Check } from "lucide-react";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";

export function PlanComparisonTable({ plans, currentPlanId }) {
  const { locale, t } = useI18n();
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
              const finalPlanName = plan.displayName || plan.name || "";
              return (
                <th key={plan.id}>
                  {finalPlanName
                    ? finalPlanName.charAt(0).toUpperCase() + finalPlanName.slice(1)
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
            const sampleFeature = plans.find((plan) => plan.features?.[key])
              ?.features[key];
            const featureName =
              locale === "ar" && sampleFeature?.name_ar
                ? sampleFeature.name_ar
                : sampleFeature?.name || t(`billing.management.usageLabels.${key}`);
            const featureDesc =
              locale === "ar" && sampleFeature?.description_ar
                ? sampleFeature.description_ar
                : sampleFeature?.description;

            return (
              <tr key={key}>
                <th>
                  <div className="billing-comparison-feature">
                    <span>{featureName}</span>
                    {featureDesc && (
                      <small>{featureDesc}</small>
                    )}
                  </div>
                </th>
                {plans.map((plan) => {
                  if (plan.isCustomBuilder) {
                    const customValue =
                      sampleFeature?.type === "boolean"
                        ? t("billing.management.optional")
                        : t("billing.management.configurable");

                    return (
                      <td key={plan.id}>
                        <strong>{customValue}</strong>
                      </td>
                    );
                  }

                  const feature = plan.features?.[key];
                  if (!feature) return <td key={plan.id}>—</td>;

                  if (feature.type === "boolean") {
                    return (
                      <td key={plan.id}>
                        <strong className="billing-comparison-included">
                          <Check size={14} aria-hidden="true" />
                          {t("billing.management.included")}
                        </strong>
                      </td>
                    );
                  }

                  if (feature.type === "configuration") {
                    return (
                      <td key={plan.id}>
                        <strong>{t("billing.management.configured")}</strong>
                      </td>
                    );
                  }

                  if (feature.limitValue === null) {
                    return (
                      <td key={plan.id}>
                        <strong>{t("common.unlimited")}</strong>
                      </td>
                    );
                  }

                  const displayUnit =
                    locale === "ar"
                      ? feature.unit_ar || feature.unit
                      : feature.unit;

                  return (
                    <td key={plan.id}>
                      <bdi>
                        {number.format(feature.limitValue)}
                        {displayUnit ? ` ${displayUnit}` : ""}
                      </bdi>
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
