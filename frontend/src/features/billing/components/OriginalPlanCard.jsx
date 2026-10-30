import { Building2, Check, Crown, Landmark, Minus, SlidersHorizontal, Sparkles, Sprout } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { getBillingOptionCount } from '../utils/billingPeriodPresentation.js';
import { formatMoney } from '../utils/money.js';
import { PLAN_MODULES } from '../api/billingApi.js';
import '../styles/PlanCardRefresh.css';

// One plan in the redesigned layout, for every plan list (landing pricing,
// choose-plan, onboarding): name and tagline, the price for the chosen
// period, the action at the same height on every card, monthly credits, then
// aligned capacity rows. Takes the plan in either shape the billing screens
// pass (the catalog plan, or the same plan through toOriginalPlan()).
const planIcons = {
  starter: Sprout,
  growth: Crown,
  enterprise: Building2,
  custom: Landmark,
};

// The capacity rows every self-serve card shows, in the same order so the
// cards line up row by row. The remaining limits are in the comparison table.
const LIMIT_ROWS = ['products', 'teamSeats', 'reports', 'storageGb', 'dataSources'];
const CUSTOM_FEATURES = ['everythingPro', 'customLimits', 'support', 'largeTeams'];

const normalizePlanName = (plan) => String(plan?.name?.en || plan?.name || '').trim().toLowerCase();

export function PlanCard({
  plan = {},
  selected,
  currentPlan = false,
  billingPeriod,
  onSelect,
  actionLabel,
  actionDisabled = false,
  actionHint,
  showTrial = true,
}) {
  const { locale, t } = useI18n();
  const planKey = plan.id || normalizePlanName(plan);
  const Icon = plan.isCustomBuilder ? SlidersHorizontal : (planIcons[planKey] || planIcons[normalizePlanName(plan)] || Crown);
  const trialDays = Number(plan.trialDays ?? plan.trialPeriodValue ?? 0);

  // The price for the chosen period: the catalog's own entry, or the
  // original model's pricing option when that is all the plan carries.
  const option = plan.pricingOptions?.find((item) => item.period === billingPeriod) || plan.pricingOptions?.[0];
  const price = plan.prices?.[billingPeriod] || (option ? {
    amount: option.totalPrice ?? option.amount,
    months: option.months ?? getBillingOptionCount(option),
    monthlyEquivalent: option.monthlyEquivalent,
    discountPercent: option.discountPercent ?? option.discount_percent ?? 0,
    currency: option.currency,
  } : null);
  const supportsPeriod = plan.isCustomBuilder || plan.selfServe === false || !plan.pricingOptions?.length
    || plan.pricingOptions.some((item) => item.period === billingPeriod);
  const currency = price?.currency || plan.currency || 'USD';
  const money = (amount) => formatMoney(amount, currency, locale, { compact: true });
  const number = new Intl.NumberFormat(locale);
  const formatLimit = (key, value) => {
    if (value === undefined || value === 0) return t('billing.plans.notIncluded');
    if (value === null) return t('billing.plans.unlimited');
    return key === 'storageGb' ? `${number.format(value)} GB` : number.format(value);
  };

  const name = plan.displayName || plan.name?.[locale] || plan.name?.en || plan.name || '';
  const taglineKey = `billing.plans.taglines.${planKey}`;
  const tagline = t(taglineKey) === taglineKey ? (plan.displayDescription || plan.description || '') : t(taglineKey);
  const custom = plan.isCustomBuilder || plan.selfServe === false;
  const priced = !custom && price && price.amount != null;
  const months = price?.months || 1;
  const monthly = price?.monthlyEquivalent ?? (price ? Math.round((price.amount / months) * 100) / 100 : null);
  const included = new Set(plan.entitlements || []);
  const modules = PLAN_MODULES.filter((module) => included.has(module));
  const missing = included.size ? PLAN_MODULES.filter((module) => !included.has(module)) : [];
  const moduleList = new Intl.ListFormat(locale, { type: 'conjunction' }).format(modules.map((module) => t(`billing.modules.${module}`)));
  const hasLimits = plan.limits && Object.keys(plan.limits).length > 0;
  const classes = ['ceopro-plan-card', plan.featured && 'is-featured', (selected || currentPlan) && 'is-selected', currentPlan && 'is-current'].filter(Boolean).join(' ');
  const label = actionLabel || (trialDays > 0
    ? t('billing.plans.trialAction', { days: trialDays, plan: name })
    : t('billing.payment.complete'));

  return (
    <article className={classes} aria-label={name}>
      {plan.featured && <span className="ceopro-plan-card__featured"><Sparkles size={12} aria-hidden="true" />{t('billing.plans.mostPopular')}</span>}
      <header className="ceopro-plan-card__head">
        <div className="ceopro-plan-card__title">
          <span className="ceopro-plan-card__icon" aria-hidden="true"><Icon size={18} /></span>
          <h3>{name}</h3>
          {currentPlan && <span className="ceopro-plan-card__current">{t('billing.management.currentPlan')}</span>}
        </div>
        <p>{tagline}</p>
      </header>

      <div className="ceopro-plan-card__price">
        {priced ? <>
          <div className="ceopro-plan-card__amount">
            <strong>{money(months > 1 ? monthly : price.amount)}</strong>
            <span>{t('billing.periods.perMonth')}</span>
          </div>
          <small>
            {months > 1 ? t('billing.periods.billedEvery', { price: money(price.amount), months }) : t('billing.periods.billedMonthly')}
            {price.discountPercent > 0 && <b>{t('billing.periods.savePercent', { percent: price.discountPercent })}</b>}
          </small>
        </> : <>
          <div className="ceopro-plan-card__amount"><strong className="is-text">{t('billing.plans.customPricing')}</strong></div>
          <small>{plan.isCustomBuilder ? t('billing.custom.previewPriceNote') : t('billing.plans.custom.description')}</small>
        </>}
      </div>

      {onSelect && <div className="ceopro-plan-card__action">
        <Button variant={plan.featured && !actionDisabled ? 'primary' : 'outline'} fullWidth onClick={() => onSelect(plan.id)}
          disabled={actionDisabled || (plan.isActive === false && !custom) || !supportsPeriod}>{label}</Button>
        {actionHint && <p className="ceopro-plan-card__hint">{actionHint}</p>}
      </div>}

      {!custom && hasLimits ? <>
        <div className="ceopro-plan-card__credits" aria-label={t('billing.plans.creditsTitle')}>
          {['dataCredits', 'aiCredits'].map((key) => <div key={key}>
            <strong>{formatLimit(key, plan.limits?.[key])}</strong>
            <span>{t(`billing.management.usageLabels.${key}`)}</span>
          </div>)}
          <small>{t('billing.plans.creditsTitle')}</small>
        </div>
        <dl className="ceopro-plan-card__limits">
          {LIMIT_ROWS.map((key) => <div key={key} className={plan.limits?.[key] === 0 || plan.limits?.[key] === undefined ? 'is-excluded' : ''}>
            <dt>{t(`billing.plans.limits.${key}`)}</dt>
            <dd><bdi>{formatLimit(key, plan.limits?.[key])}</bdi></dd>
          </div>)}
        </dl>
        {(missing.length > 0 || (showTrial && trialDays > 0)) && <ul className="ceopro-plan-card__features">
          {/* Modules every plan has are listed once, under the grid (PlanSharedFeatures). */}
          {missing.length > 0 && modules.length > 0 && <li><Check size={15} aria-hidden="true" /><span>{moduleList}</span></li>}
          {missing.map((module) => <li key={module} className="is-excluded"><Minus size={15} aria-hidden="true" /><span>{t(`billing.modules.${module}`)} - {t('billing.modules.notIncluded')}</span></li>)}
          {showTrial && trialDays > 0 && <li className="is-trial"><Check size={15} aria-hidden="true" /><span>{plan.trialLimits?.dataCredits != null
            ? t('billing.plans.trialLine', { days: trialDays, data: number.format(plan.trialLimits.dataCredits), ai: number.format(plan.trialLimits.aiCredits ?? 0) })
            : t('billing.plans.trialIncluded', { days: trialDays })}</span></li>}
        </ul>}
      </> : <ul className="ceopro-plan-card__features is-custom">
        {CUSTOM_FEATURES.map((key) => <li key={key}><Check size={15} aria-hidden="true" /><span>{t(`billing.features.${key}`)}</span></li>)}
      </ul>}
    </article>
  );
}

// What every self-serve plan has in common, said once instead of on each card.
export function PlanSharedFeatures({ plans }) {
  const { locale, t } = useI18n();
  const selfServe = plans.filter((plan) => plan.selfServe);
  const common = PLAN_MODULES.filter((module) => selfServe.length && selfServe.every((plan) => plan.entitlements?.includes(module)));
  const list = new Intl.ListFormat(locale, { type: 'conjunction' }).format(common.map((module) => t(`billing.modules.${module}`)));
  return <ul className="ceopro-plan-shared">
    {common.length === PLAN_MODULES.length && <li><Check size={15} aria-hidden="true" />{t('billing.plans.allModules', { modules: list })}</li>}
    {/* No fixed competitor count: discovery runs within the Data Credits. */}
    <li><Check size={15} aria-hidden="true" />{t('billing.features.competitorsByBudget')}</li>
  </ul>;
}
