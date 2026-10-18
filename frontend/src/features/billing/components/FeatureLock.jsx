import { LockKeyhole } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import Button from '../../../shared/components/ui/Button.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import '../styles/Entitlements.css';

const formatDate = (value, locale) => {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat(locale === 'ar' ? 'ar-JO' : 'en-US', {
    dateStyle: 'medium',
  }).format(date);
};

export function FeatureLock({ state, reason, compact = false, title }) {
  const { t, locale } = useI18n();
  const navigate = useNavigate();
  const name = title
    || (locale === 'ar' ? state?.feature?.name_ar : state?.feature?.name)
    || state?.feature?.name
    || state?.featureCode
    || t('billing.entitlements.feature');

  const lockReason = reason
    || (!state?.included
      ? 'notIncluded'
      : state?.aggregationType === 'max'
        ? 'capacityReached'
        : 'quotaExhausted');

  const resetDate = state?.resetCycle === 'billing_period'
    ? formatDate(state?.periodEnd, locale)
    : null;

  const description = lockReason === 'notIncluded'
    ? t('billing.entitlements.notIncluded', { feature: name })
    : lockReason === 'capacityReached'
      ? t('billing.entitlements.capacityReached', {
          current: state?.currentUsage ?? 0,
          limit: state?.limit ?? 0,
        })
      : `${t('billing.entitlements.quotaExhausted', {
          current: state?.currentUsage ?? 0,
          limit: state?.limit ?? 0,
        })}${resetDate ? ` ${t('billing.entitlements.resetsOn', { date: resetDate })}` : ''}`;

  const action = (
    <Button
      size="sm"
      variant="outline"
      onClick={() => navigate(routePaths.billingPlans)}
    >
      {t('billing.entitlements.viewPlans')}
    </Button>
  );

  if (compact) {
    return (
      <div className="ceopro-feature-lock ceopro-feature-lock--compact" role="status">
        <span className="ceopro-feature-lock__icon"><LockKeyhole size={18} aria-hidden="true" /></span>
        <div className="ceopro-feature-lock__copy">
          <strong>{name}</strong>
          <span>{description}</span>
        </div>
        {action}
      </div>
    );
  }

  return (
    <div className="ceopro-feature-lock-page">
      <EmptyState
        icon={<LockKeyhole size={28} aria-hidden="true" />}
        title={t('billing.entitlements.lockedTitle', { feature: name })}
        description={description}
        action={action}
      />
    </div>
  );
}
