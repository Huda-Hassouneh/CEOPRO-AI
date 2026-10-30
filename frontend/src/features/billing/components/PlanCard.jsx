import { PlanCard as OriginalPlanCard, PlanSharedFeatures } from './OriginalPlanCard.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { toOriginalPlan } from '../api/originalBillingModel.js';

export { PlanSharedFeatures };

// The catalog plan (billingApi.mapPlan) on the shared card. onAction receives
// the plan itself (the landing page reads plan.selfServe); onSelect, as on the
// other billing screens, receives its id.
export function PlanCard({ plan, onAction, onSelect, ...props }) {
  const { locale } = useI18n();
  const value = toOriginalPlan(plan);
  const select = onSelect || (onAction ? () => onAction(plan) : undefined);
  return <OriginalPlanCard {...props} plan={{ ...value, displayName: value.displayName || (locale === 'ar' ? value.name_ar || value.name : value.name) }} onSelect={select} />;
}
