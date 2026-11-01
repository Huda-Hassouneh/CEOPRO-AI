import { Link, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { useAuthStore } from '../../auth/store/authStore.js';
import { platformBillingApi } from '../../platform/platformBillingApi.js';
import './BillingGuidance.css';

const steps = [
  ['provider-accounting', 'provider'], ['features', 'features'],
  ['plan-features', 'planFeatures'], ['pricing-studio', 'policy'],
  ['pricing-studio', 'analysis'], ['plans', 'plans'],
  ['custom-quotes', 'custom'], ['promos', 'promos'], ['subscriptions', 'subscriptions'],
];

export function BillingTabLink({ tab, children, className = '' }) {
  const location = useLocation();
  const params = new URLSearchParams(location.search);
  params.set('tab', tab);
  params.delete('plan');
  return <Link className={className} to={`${location.pathname}?${params.toString()}`}>{children}</Link>;
}

export function BillingSetupGuide({ plans, features }) {
  const { t } = useI18n();
  const actor = useAuthStore(state => state.user?.id || state.user?.user_id);
  const query = useQuery({ queryKey: ['platform', actor, 'pricing-studio'], queryFn: platformBillingApi.pricingStudio, retry: false });
  const data = query.data;
  const providerPaths = data?.provider_readiness?.providers || [];
  const rates = providerPaths.flatMap(path => path.rates || []);
  const verified = rates.filter(rate => rate.status === 'VERIFIED').length;
  const missing = rates.filter(rate => rate.status === 'MISSING').length;
  const hasPolicy = Boolean(data?.selected_policy);
  const statuses = {
    // Optional provider alternatives cannot be treated as mandatory setup blockers.
    provider: 'INFO',
    features: features.length ? 'READY' : 'INCOMPLETE',
    planFeatures: 'INFO', policy: data ? (hasPolicy ? 'READY' : 'INCOMPLETE') : 'INFO',
    analysis: 'INFO', plans: plans.length ? 'READY' : 'INCOMPLETE',
    custom: 'INFO', promos: 'INFO', subscriptions: 'INFO',
  };
  const values = {
    provider: data ? t('billing.catalog.guided.providerCount', { verified, total: rates.length, missing }) : '',
    features: features.length ? t('billing.catalog.guided.featureCount', { count: features.length }) : '',
    plans: plans.length ? t('billing.catalog.guided.planCount', { count: plans.filter(plan => plan.isActive).length }) : '',
  };
  return <section className="billing-guided-overview" aria-label={t('billing.catalog.guided.title')}>
    <div className="billing-guided-heading"><div><h2>{t('billing.catalog.guided.title')}</h2><p>{t('billing.catalog.guided.intro')}</p></div>
      <details><summary>{t('billing.catalog.guided.howItFits')}</summary><p>{t('billing.catalog.guided.flow')}</p></details>
    </div>
    <details className="billing-guided-checklist"><summary>{t('billing.catalog.guided.setupTitle')}</summary>
      <p>{t('billing.catalog.guided.statusNote')}</p>
      {query.isError && <p role="status">{t('billing.catalog.guided.setupUnavailable')}</p>}
      <ol>{steps.map(([tab, key]) => <li key={key}>
        <span className={`billing-guided-status status-${statuses[key]}`}>{t(`billing.catalog.guided.status.${statuses[key]}`)}</span>
        <BillingTabLink tab={tab}>{t(`billing.catalog.guided.steps.${key}`)}</BillingTabLink>
        {values[key] && <small>{values[key]}</small>}
      </li>)}</ol>
      <p className="billing-guided-next">{t('billing.catalog.guided.next')}: <BillingTabLink tab="pricing-studio">{t(`billing.catalog.guided.steps.${!hasPolicy && data ? 'policy' : 'analysis'}`)}</BillingTabLink></p>
    </details>
  </section>;
}

const nextTab = {
  plans: 'pricing-studio', 'pricing-studio': 'provider-accounting',
  'custom-plans': 'custom-quotes', 'custom-quotes': 'provider-accounting',
  promos: 'plans', features: 'plan-features', 'plan-features': 'plans',
  subscriptions: 'plans', 'provider-accounting': 'pricing-studio',
};

export function BillingTabGuide({ tab }) {
  const { t } = useI18n();
  return <details className="billing-tab-guide">
    <summary>{t('billing.catalog.guided.aboutTab')}</summary>
    <dl>{['purpose', 'when', 'depends', 'affects', 'doesNot'].map(key => <div key={key}>
      <dt>{t(`billing.catalog.guided.labels.${key}`)}</dt>
      <dd>{t(`billing.catalog.guided.tabs.${tab}.${key}`)}</dd>
    </div>)}</dl>
    <BillingTabLink tab={nextTab[tab]}>{t('billing.catalog.guided.recommendedNext')}: {t(`billing.catalog.guided.tabNames.${nextTab[tab]}`)}</BillingTabLink>
  </details>;
}
