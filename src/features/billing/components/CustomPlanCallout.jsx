import { SlidersHorizontal } from "lucide-react";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import Button from "../../../shared/components/ui/Button.jsx";

export function CustomPlanCallout({
  onSelect,
  disabled = false,
  actionLabel,
}) {
  const { t } = useI18n();

  return (
    <aside className="ceopro-custom-plan-callout">
      <span className="ceopro-custom-plan-callout__icon" aria-hidden="true">
        <SlidersHorizontal size={22} />
      </span>

      <div className="ceopro-custom-plan-callout__copy">
        <small>{t("billing.plans.custom.calloutEyebrow")}</small>
        <h3>{t("billing.plans.custom.calloutTitle")}</h3>
        <p>{t("billing.plans.custom.calloutDescription")}</p>
      </div>

      <Button
        variant="outline"
        onClick={onSelect}
        disabled={disabled}
      >
        {actionLabel || t("billing.plans.custom.action")}
      </Button>
    </aside>
  );
}
