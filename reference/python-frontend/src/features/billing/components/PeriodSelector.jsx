import SegmentedControl from '../../../shared/components/ui/SegmentedControl.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { BILLING_PERIODS } from '../api/billingApi.js';

export function PeriodSelector({ plans, value, onChange, name = 'billing-period' }) {
  const { t } = useI18n();
  const options = BILLING_PERIODS.filter((period) => plans.some((plan) => plan.prices?.[period.value])).map((period) => {
    const discounts = plans.map((plan) => plan.prices?.[period.value]?.discountPercent).filter((d) => d != null);
    const same = discounts.length && discounts.every((d) => d === discounts[0]) ? discounts[0] : 0;
    return {
      value: period.value,
      label: period.months === 1 ? t('billing.periods.monthly') : t('billing.periods.monthCountLabel', { months: period.months }),
      badge: same ? t('billing.periods.savePercent', { percent: same }) : undefined,
    };
  });
  return <SegmentedControl name={name} value={value} options={options} onChange={onChange} ariaLabel={t('billing.periods.label')} />;
}
