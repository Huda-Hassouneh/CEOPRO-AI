import { Building2, Check, Crown, Landmark, Minus, Sparkles, Sprout } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { formatMoney } from '../utils/money.js';
import { PLAN_MODULES } from '../api/billingApi.js';

const planIcons = { starter: Sprout, growth: Crown, enterprise: Building2, custom: Landmark };
// The capacity rows every self-serve card shows, in the same order so the
// cards line up row by row. The remaining limits are in the comparison table.
const LIMIT_ROWS = ['products', 'teamSeats', 'reports', 'storageGb', 'dataSources'];
const CUSTOM_FEATURES = ['everythingPro', 'customLimits', 'support', 'largeTeams'];

export function PlanCard({ plan, billingPeriod, currentPlan = false, onAction, actionLabel, actionDisabled = false, actionHint, actionNote, actionLoading = false, showTrial = true }) {
  const { locale, t } = useI18n();
  const Icon = planIcons[plan.id] || Crown;
  const price = plan.prices?.[billingPeriod];
  const number = new Intl.NumberFormat(locale);
  const money = (amount) => formatMoney(amount, price.currency, locale, { compact: true });
  const formatLimit = (key, value) => {
    if (value === undefined || value === 0) return t('billing.plans.notIncluded');
    if (value === null) return t('billing.plans.unlimited');
    return key === 'storageGb' ? `${number.format(value)} GB` : number.format(value);
  };
  const included = new Set(plan.entitlements || []);
  const modules = PLAN_MODULES.filter((module) => included.has(module));
  const missing = PLAN_MODULES.filter((module) => !included.has(module));
  const moduleList = new Intl.ListFormat(locale, { type: 'conjunction' }).format(modules.map((module) => t(`billing.modules.${module}`)));
  const name = plan.name?.[locale] || plan.name?.en;
  const tagline = t(`billing.plans.taglines.${plan.id}`);
  const priced = plan.selfServe && price;
  const classes = ['ceopro-plan-card', plan.featured && 'is-featured', currentPlan && 'is-current'].filter(Boolean).join(' ');

  return (
    <article className={classes} aria-label={name}>
      {plan.featured && <span className="ceopro-plan-card__featured"><Sparkles size={12} aria-hidden="true" />{t('billing.plans.mostPopular')}</span>}
      <header className="ceopro-plan-card__head">
        <div className="ceopro-plan-card__title">
          <span className="ceopro-plan-card__icon" aria-hidden="true"><Icon size={18} /></span>
          <h3>{name}</h3>
          {currentPlan && <span className="ceopro-plan-card__current">{t('billing.management.currentPlan')}</span>}
        </div>
        <p>{tagline === `billing.plans.taglines.${plan.id}` ? '' : tagline}</p>
      </header>

      <div className="ceopro-plan-card__price">
        {priced ? <>
          <div className="ceopro-plan-card__amount">
            <strong>{money(price.months > 1 ? price.monthlyEquivalent : price.amount)}</strong>
            <span>{t('billing.periods.perMonth')}</span>
          </div>
          <small>
            {price.months > 1 ? t('billing.periods.billedEvery', { price: money(price.amount), months: price.months }) : t('billing.periods.billedMonthly')}
            {price.discountPercent > 0 && <b>{t('billing.periods.savePercent', { percent: price.discountPercent })}</b>}
          </small>
        </> : <>
          <div className="ceopro-plan-card__amount"><strong className="is-text">{t('billing.plans.customPricing')}</strong></div>
          <small>{t('billing.plans.custom.description')}</small>
        </>}
      </div>

      {onAction && <div className="ceopro-plan-card__action">
        <Button variant={plan.featured && !actionDisabled ? 'primary' : 'outline'} fullWidth onClick={() => onAction(plan)} disabled={actionDisabled} loading={actionLoading}>{actionLabel}</Button>
        {(actionHint || actionNote) && <p className="ceopro-plan-card__hint">{actionHint || actionNote}</p>}
      </div>}

      {plan.selfServe ? <>
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
        {(missing.length > 0 || (showTrial && plan.trialDays > 0)) && <ul className="ceopro-plan-card__features">
          {/* Modules every plan has are listed once, under the grid (PlanSharedFeatures). */}
          {missing.length > 0 && modules.length > 0 && <li><Check size={15} aria-hidden="true" /><span>{moduleList}</span></li>}
          {missing.map((module) => <li key={module} className="is-excluded"><Minus size={15} aria-hidden="true" /><span>{t(`billing.modules.${module}`)} - {t('billing.modules.notIncluded')}</span></li>)}
          {showTrial && plan.trialDays > 0 && <li className="is-trial"><Check size={15} aria-hidden="true" /><span>{plan.trialLimits?.dataCredits != null
            ? t('billing.plans.trialLine', { days: plan.trialDays, data: number.format(plan.trialLimits.dataCredits), ai: number.format(plan.trialLimits.aiCredits ?? 0) })
            : t('billing.plans.trialIncluded', { days: plan.trialDays })}</span></li>}
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
