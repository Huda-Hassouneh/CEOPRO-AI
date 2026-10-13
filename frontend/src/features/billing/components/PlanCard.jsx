import { Building2, Check, Crown, Landmark, Minus, Sprout } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { formatMoney } from '../utils/money.js';
import { PLAN_MODULES } from '../api/billingApi.js';

const planIcons = { starter: Sprout, growth: Crown, enterprise: Building2, custom: Landmark };
// A limit of 0 means the plan doesn't include that feature (shown as a module instead).
const FEATURE_ROWS = ['products', 'aiTokens', 'documentProcessingMb', 'storageGb', 'dataSources', 'competitors', 'sentimentRecords', 'imageGenerations'];

export function PlanCard({ plan, billingPeriod, currentPlan = false, onAction, actionLabel, actionDisabled = false, actionHint }) {
  const { locale, t } = useI18n();
  const Icon = planIcons[plan.id] || Crown;
  const price = plan.prices?.[billingPeriod];
  const number = new Intl.NumberFormat(locale);
  const formatLimit = (key, value) => value === null ? '∞' : key === 'storageGb' ? `${number.format(value)} GB` : number.format(value);
  const included = new Set(plan.entitlements || []);
  return (
    <article className={`ceopro-plan-card ${currentPlan ? 'is-selected is-current' : ''} ${plan.featured ? 'is-featured' : ''}`.trim()}>
      {plan.featured && <span className="ceopro-plan-card__featured">{t('billing.plans.mostPopular')}</span>}
      <header>
        <span className="ceopro-plan-card__icon"><Icon size={21} /></span>
        <div>
          <h2>{plan.name?.[locale] || plan.name?.en}{currentPlan && <span className="ceopro-plan-card__current">{t('billing.management.currentPlan')}</span>}</h2>
          <p>{t(`billing.plans.${plan.id}.description`)}</p>
        </div>
      </header>
      <div className="ceopro-plan-card__price">
        {!plan.selfServe || !price
          ? <strong>{t('billing.plans.customPricing')}</strong>
          : <>
            <strong>{formatMoney(price.amount, price.currency, locale)}</strong>
            <span>/ {price.months > 1 ? t('billing.periods.monthCount', { months: price.months }) : t('billing.periods.month')}</span>
            {price.months > 1 && <small>{t('billing.periods.monthlyEquivalent', { price: formatMoney(price.monthlyEquivalent, price.currency, locale) })}</small>}
          </>}
      </div>
      <ul>
        {plan.selfServe
          ? <>
            {FEATURE_ROWS.filter((key) => key in plan.limits && plan.limits[key] !== 0).map((key) => (
              <li key={key}><Check size={15} aria-hidden="true" /><span>{t(`billing.features.${key === 'storageGb' ? 'storage' : key}`, { value: formatLimit(key, plan.limits[key]) })}</span></li>
            ))}
            {PLAN_MODULES.map((module) => (
              <li key={module} className={included.has(module) ? '' : 'is-excluded'}>
                {included.has(module) ? <Check size={15} aria-hidden="true" /> : <Minus size={15} aria-hidden="true" />}
                <span>{t(`billing.modules.${module}`)}{included.has(module) ? '' : ` - ${t('billing.modules.notIncluded')}`}</span>
              </li>
            ))}
          </>
          : ['everythingEnterprise', 'customLimits', 'support', 'largeTeams'].map((key) => (
            <li key={key}><Check size={15} aria-hidden="true" /><span>{t(`billing.features.${key}`)}</span></li>
          ))}
        {plan.trialDays > 0 && <li><Check size={15} aria-hidden="true" /><span>{t('billing.plans.trialIncluded', { days: plan.trialDays })}</span></li>}
      </ul>
      {onAction && <Button variant={plan.featured && !actionDisabled ? 'primary' : 'outline'} fullWidth onClick={() => onAction(plan)} disabled={actionDisabled}>{actionLabel}</Button>}
      {actionHint && <p className="ceopro-plan-card__hint">{actionHint}</p>}
    </article>
  );
}
