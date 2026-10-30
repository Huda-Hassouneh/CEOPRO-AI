import { PlanCard as OriginalPlanCard } from './OriginalPlanCard.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { toOriginalPlan } from '../api/originalBillingModel.js';
export function PlanCard({ plan, onAction, onSelect, ...props }) {
  const { locale } = useI18n();
  const value = toOriginalPlan(plan);
  return <OriginalPlanCard {...props} plan={{ ...value, displayName: value.displayName || (locale === 'ar' ? value.name_ar || value.name : value.name) }} onSelect={onSelect || onAction} />;
}
