import { Bot, Boxes, Check, Crown, Database, FileText, Landmark, Plug, RefreshCw, Sprout, Target, Users } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { CUSTOM_PLAN_SUMMARY_FIELDS, formatPreviewUsd, getBillingPeriod, getPlanFeatureRows, getPreviewPlan, getPreviewPlanPrice } from '../config/billingPreviewData.js';

const customIcons = { products: Boxes, competitors: Target, ragQueries: Bot, reports: FileText, storageGb: Database, teamMembers: Users, integrations: Plug, updateFrequency: RefreshCw };
const planIcons = { standard: Sprout, pro: Crown, custom: Landmark };

export function PlanSummaryCard({ planId, customPlan, quote, billingPeriod, checkoutMode = 'paid' }) {
  const { locale, t } = useI18n();
  const plan = getPreviewPlan(planId);
  const isCustom = plan.id === 'custom';
  const isTrial = plan.trialDays > 0 && checkoutMode === 'trial';
  const pricing = getPreviewPlanPrice(plan.id, billingPeriod);
  const previewPrice = isCustom ? quote.amount : pricing?.total ?? 0;
  const dueToday = isTrial ? 0 : previewPrice;
  const PlanIcon = planIcons[plan.id];
  const period = getBillingPeriod(billingPeriod, plan.id);

  return (
    <aside className="ceopro-plan-summary">
      <header>
        <div className="ceopro-plan-summary__identity">
          <span className="ceopro-plan-summary__icon"><PlanIcon size={17} /></span>
          <div><h2>{isCustom ? t('billing.custom.summaryTitle') : t('billing.payment.yourPlan')}</h2><small>{(plan.description?.[locale] || t(plan.descriptionKey))}</small></div>
        </div>
        <span>{isTrial ? t('billing.payment.proTrial') : (plan.name?.[locale] || t(plan.nameKey))}</span>
      </header>
      {isCustom ? (
        <ul>
          {CUSTOM_PLAN_SUMMARY_FIELDS.map((key) => {
            const Icon = customIcons[key];
            const rawValue = customPlan[key];
            const displayValue = key === 'storageGb'
              ? `${rawValue} GB`
              : typeof rawValue === 'number'
                ? new Intl.NumberFormat(locale === 'ar' ? 'ar-JO' : 'en-US').format(rawValue)
                : t(`billing.custom.summaryValues.${rawValue}`);
            return <li key={key}><Icon size={14} /><span>{t(`billing.custom.summaryLabels.${key}`)}</span><strong>{displayValue}</strong></li>;
          })}
        </ul>
      ) : (
        <ul>{getPlanFeatureRows(plan).map(({ key, value }) => <li className="ceopro-plan-summary__feature" key={key}><Check size={14} /><span>{t(`billing.custom.summaryLabels.${key}`)}</span><strong>{value}</strong></li>)}</ul>
      )}
      <div className="ceopro-plan-summary__price">
        <div><span>{t('billing.payment.billingCycle')}</span><strong>{period.months === 1 ? t('billing.periods.monthly') : t('billing.periods.monthCountLabel', { months: period.months })}</strong></div>
        {!isCustom && pricing && (
          <>
            <div><span>{t('billing.payment.subtotal')}</span><strong>{formatPreviewUsd(pricing.base, locale)}</strong></div>
            <div><span>{t('billing.payment.discount', { percent: pricing.discountPercent })}</span><strong>{formatPreviewUsd(-pricing.discount, locale)}</strong></div>
          </>
        )}
        {isTrial ? (
          <>
            <div><span>{t('billing.payment.afterTrial', { days: plan.trialDays })}</span><strong>{formatPreviewUsd(pricing?.total ?? plan.monthlyPrice, locale)}</strong></div>
            <div><span className="is-success">{t('billing.payment.trial', { days: plan.trialDays })}</span><strong className="is-success">{formatPreviewUsd(0, locale)}</strong></div>
          </>
        ) : (
          <div><span>{isCustom ? t('billing.custom.estimatedPrice') : t('billing.payment.previewTotal')}</span><strong>{formatPreviewUsd(previewPrice, locale)}{isCustom ? ` / ${t('billing.periods.month')}` : ''}</strong></div>
        )}
      </div>
      <div className="ceopro-plan-summary__total"><span>{t('billing.payment.totalDueToday')}</span><strong className={isTrial ? 'is-success' : ''}>{formatPreviewUsd(dueToday, locale)}</strong></div>
      {isCustom && <><p>{t('billing.custom.previewPriceNote')}</p><div className="ceopro-plan-summary__helper"><strong>{t('billing.custom.helperTitle')}</strong><span>{t('billing.custom.helperDescription')}</span></div></>}
    </aside>
  );
}

