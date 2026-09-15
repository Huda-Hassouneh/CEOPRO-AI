import { Check } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';

export function PlanComparisonTable({ plans, currentPlanId }) {
  const { locale, t } = useI18n();
  const number = new Intl.NumberFormat(locale);
  const limitKeys = [...new Set(plans.flatMap((plan) => Object.keys(plan.limits || {})))];
  if (!plans.length || !limitKeys.length) return null;
  return <div className="billing-comparison-wrap"><table className="billing-comparison-table"><thead><tr><th>{t('billing.management.comparison.limit')}</th>{plans.map((plan) => <th key={plan.id}>{plan.name?.[locale] || t(plan.nameKey)}{currentPlanId === plan.id && <span><Check size={11} />{t('billing.management.currentPlan')}</span>}</th>)}</tr></thead><tbody>{limitKeys.map((key) => <tr key={key}><th>{t(`billing.management.usageLabels.${key}`)}</th>{plans.map((plan) => <td key={plan.id}>{plan.limits?.[key] === null ? '∞' : plan.limits?.[key] === undefined ? t('billing.management.customLimit') : <bdi>{number.format(plan.limits[key])}{key === 'storageGb' ? ` ${t('billing.management.gb')}` : ''}</bdi>}</td>)}</tr>)}</tbody></table></div>;
}
