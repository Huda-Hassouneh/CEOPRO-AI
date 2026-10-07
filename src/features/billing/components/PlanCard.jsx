import { Check, Crown, SlidersHorizontal, Sprout } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import {
  describeBillingOption,
  getBillingOptionCount,
  getBillingOptionUnit,
} from '../utils/billingPeriodPresentation.js';

const planIcons = {
  starter: Sprout,
  growth: Crown,
  enterprise: Crown,
};

const FEATURE_PRIORITY = [
  'dashboard_analytics',
  'data_integration',
  'product_management',
  'rag_assistant',
  'document_extraction',
  'document_storage_mb',
  'connected_data_sources',
  'market_intelligence',
  'demand_prediction',
  'competitor_management',
  'tracked_competitors',
  'sentiment_analysis',
  'tracked_products',
];

const normalizePlanName = (plan) => String(plan?.name || '').trim().toLowerCase();

const getFeatureLabel = (featureCode, feature, locale) => {
  if (locale === 'ar' && feature?.name_ar) return feature.name_ar;
  return feature?.name || featureCode;
};

const getFeatureRank = (featureCode) => {
  const index = FEATURE_PRIORITY.indexOf(featureCode);
  return index === -1 ? FEATURE_PRIORITY.length : index;
};

const sortFeatureEntries = (entries) =>
  [...entries].sort(([leftCode], [rightCode]) => {
    const rankDifference = getFeatureRank(leftCode) - getFeatureRank(rightCode);
    return rankDifference || leftCode.localeCompare(rightCode);
  });

const stableJson = (value) => {
  if (value === null || value === undefined) return '';
  try {
    return JSON.stringify(value, Object.keys(value || {}).sort());
  } catch {
    return String(value);
  }
};

const hasMeaningfulUpgrade = (feature, previousFeature) => {
  if (!previousFeature) return true;

  if (feature?.type === 'limit') {
    if (feature.limitValue === null && previousFeature.limitValue !== null) return true;
    if (feature.limitValue === null || previousFeature.limitValue === null) return false;

    const current = Number(feature.limitValue);
    const previous = Number(previousFeature.limitValue);
    return Number.isFinite(current) && Number.isFinite(previous) && current > previous;
  }

  if (feature?.type === 'configuration') {
    return stableJson(feature.configuration) !== stableJson(previousFeature.configuration);
  }

  return false;
};

const getCompactFeatureEntries = (plan, previousPlan, maxHighlights) => {
  const entries = sortFeatureEntries(Object.entries(plan.features || {}));

  if (!previousPlan) {
    return entries.slice(0, maxHighlights);
  }

  const previousFeatures = previousPlan.features || {};
  const differences = entries.filter(([featureCode, feature]) =>
    hasMeaningfulUpgrade(feature, previousFeatures[featureCode])
  );

  return differences.slice(0, maxHighlights);
};

const formatScaledLimit = (value, rawUnit, displayUnit, locale, numberFormatter) => {
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) {
    return {
      value: value ?? 0,
      unit: displayUnit,
    };
  }

  const normalizedUnit = String(rawUnit || '').toLowerCase();

  if (normalizedUnit === 'kb' && numericValue >= 1024) {
    const mb = numericValue / 1024;
    return {
      value: numberFormatter.format(mb),
      unit: locale === 'ar' ? 'ميجابايت' : 'MB',
    };
  }

  if (normalizedUnit === 'mb' && numericValue >= 1024) {
    const gb = numericValue / 1024;
    return {
      value: numberFormatter.format(gb),
      unit: locale === 'ar' ? 'جيجابايت' : 'GB',
    };
  }

  return {
    value: numberFormatter.format(numericValue),
    unit: displayUnit,
  };
};

export function PlanCard({
  plan = {},
  selected,
  currentPlan = false,
  billingPeriod,
  onSelect,
  actionLabel,
  actionDisabled = false,
  compactSummary = false,
  previousPlan = null,
  maxHighlights = 5,
}) {
  const { locale, t } = useI18n();
  const planNameSafe = normalizePlanName(plan);
  const Icon = plan.isCustomBuilder ? SlidersHorizontal : (planIcons[planNameSafe] || Sprout);
  const hasTrial = Number(plan.trialPeriodValue) > 0;
  const selectedPricingOption =
    plan.pricingOptions?.find((option) => option.period === billingPeriod) ||
    plan.pricingOptions?.[0];
  const supportsPeriod =
    plan.isCustomBuilder ||
    plan.pricingOptions?.some((option) => option.period === billingPeriod);
  const intervalUnit = getBillingOptionUnit(selectedPricingOption || {});
  const intervalCount = getBillingOptionCount(selectedPricingOption || {});
  const isMultiMonth =
    intervalUnit !== 'day' && (selectedPricingOption?.months ?? intervalCount) > 1;
  const finalTotal = selectedPricingOption?.totalPrice ?? plan.basePrice ?? 0;
  const monthlyEquivalent =
    selectedPricingOption?.monthlyEquivalent ?? plan.basePrice ?? 0;

  const formatCurrency = (amount) =>
    new Intl.NumberFormat(locale === 'ar' ? 'ar-JO' : 'en-US', {
      style: 'currency',
      currency: plan.currency || 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(amount || 0);

  const numberFormatter = new Intl.NumberFormat(locale === 'ar' ? 'ar-JO' : 'en-US', {
    maximumFractionDigits: 1,
  });

  const finalPlanName = plan.displayName || plan.name || '';
  const finalDescription = plan.displayDescription || plan.description || '';
  const compactEntries = compactSummary
    ? getCompactFeatureEntries(plan, previousPlan, maxHighlights)
    : [];

  const renderFeatureLine = (featureCode, feature) => {
    const featureName = getFeatureLabel(featureCode, feature, locale);

    if (feature?.type === 'boolean' || feature?.type === 'configuration') {
      return featureName;
    }

    if (feature?.type !== 'limit') {
      return featureName;
    }

    if (feature?.limitValue === null) {
      return `${t('common.unlimited')} ${featureName}`;
    }

    const displayUnit =
      locale === 'ar' ? feature?.unit_ar || feature?.unit : feature?.unit;
    const scaled = formatScaledLimit(
      feature.limitValue,
      feature?.unit,
      displayUnit,
      locale,
      numberFormatter
    );

    return `${scaled.value}${scaled.unit ? ` ${scaled.unit}` : ''} ${featureName}`;
  };

  const previousPlanName =
    previousPlan?.displayName || previousPlan?.name || '';

  return (
    <article
      className={`ceopro-plan-card ${compactSummary ? 'is-compact' : ''} ${
        selected || currentPlan ? 'is-selected' : ''
      } ${plan.featured ? 'is-featured' : ''} ${currentPlan ? 'is-current' : ''}`.trim()}
    >
      {plan.featured && (
        <span className="ceopro-plan-card__featured">{t('billing.plans.mostPopular')}</span>
      )}

      <header>
        <span className="ceopro-plan-card__icon"><Icon size={21} /></span>
        <div>
          <h2>
            {finalPlanName}
            {currentPlan && (
              <span className="ceopro-plan-card__current">
                {t('billing.management.currentPlan')}
              </span>
            )}
          </h2>
          <p>{finalDescription}</p>
        </div>
      </header>

      <div className="ceopro-plan-card__price">
        {plan.isCustomBuilder ? (
          <>
            <strong>{t('billing.plans.customPricing')}</strong>
            <small>
              {t('billing.custom.previewPriceNote') ||
                'Your price is calculated securely from the features and quotas you choose.'}
            </small>
          </>
        ) : (
          <>
            <strong>{formatCurrency(finalTotal)}</strong>
            <span>
              / {intervalUnit === 'day'
                ? describeBillingOption(selectedPricingOption, t)
                : intervalUnit === 'year'
                  ? describeBillingOption(selectedPricingOption, t)
                  : isMultiMonth
                    ? t('billing.periods.monthCount', { months: intervalCount })
                    : t('billing.periods.month')}
            </span>
            {isMultiMonth && (
              <small>
                {t('billing.periods.monthlyEquivalent', {
                  price: formatCurrency(monthlyEquivalent),
                })}
              </small>
            )}
          </>
        )}
      </div>

      {compactSummary ? (
        <div className="ceopro-plan-card__feature-summary">
          <p className="ceopro-plan-card__feature-heading">
            {previousPlanName
              ? t('billing.plans.includesPrevious', { plan: previousPlanName })
              : t('billing.plans.highlights')}
          </p>
          {compactEntries.length ? (
            <ul>
              {compactEntries.map(([featureCode, feature]) => (
                <li key={featureCode}>
                  <Check size={15} aria-hidden="true" />
                  <span>{renderFeatureLine(featureCode, feature)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="ceopro-plan-card__capacity-note">
              {t('billing.plans.higherCapacity')}
            </p>
          )}
        </div>
      ) : (
        <ul>
          {Object.entries(plan.features || {}).map(([featureCode, feature]) => (
            <li key={featureCode}>
              <Check size={15} aria-hidden="true" />
              <span>{renderFeatureLine(featureCode, feature)}</span>
            </li>
          ))}
        </ul>
      )}

      <Button
        variant={plan.featured && !actionDisabled ? 'primary' : 'outline'}
        fullWidth
        onClick={() => onSelect?.(plan.id)}
        disabled={actionDisabled || plan.isActive === false || !supportsPeriod}
      >
        {actionLabel || (hasTrial
          ? t('billing.plans.trialAction', {
              days: plan.trialPeriodValue,
              plan: finalPlanName,
            })
          : t('billing.payment.complete'))}
      </Button>
    </article>
  );
}
