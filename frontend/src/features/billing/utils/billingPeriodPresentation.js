export const getBillingOptionUnit = (option) => option.intervalUnit || 'month';
export const getBillingOptionCount = (option) => option.intervalCount ?? option.months ?? 1;

export const describeBillingOption = (option, t) => {
  const count = getBillingOptionCount(option);
  const unit = getBillingOptionUnit(option);
  if (unit === 'day') return count === 1 ? t('billing.periods.oneDayLabel')
    : t('billing.periods.dayCountLabel', { days: count });
  if (unit === 'year') return count === 1 ? t('billing.periods.oneYearLabel')
    : t('billing.periods.yearCountLabel', { years: count });
  return count === 1 ? t('billing.periods.monthly')
    : t('billing.periods.monthCountLabel', { months: count });
};

export const listBillingPeriods = (plans) => {
  const periods = new Map();
  for (const plan of plans) {
    for (const option of plan?.pricingOptions || []) {
      if (!option?.period) continue;
      const existing = periods.get(option.period);
      if (existing) {
        if (getBillingOptionUnit(existing) !== getBillingOptionUnit(option) ||
            getBillingOptionCount(existing) !== getBillingOptionCount(option)) existing.mixedIntervals = true;
        if (existing.discountPercent !== option.discountPercent) existing.mixedDiscounts = true;
      } else periods.set(option.period, { ...option });
    }
  }
  return [...periods.values()].sort((a, b) =>
    (a.months ?? getBillingOptionCount(a)) - (b.months ?? getBillingOptionCount(b)));
};
