import { Check, Clock3, X } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';

export function SubscriptionResult({ status, onPrimary, onBack, onRetry, checking = false }) {
  const { t } = useI18n();
  const success = status === 'confirmed';
  const pending = status === 'pending' || status === 'checking';
  const error = status === 'error';
  const Icon = success ? Check : pending ? Clock3 : X;
  const copyKey = success ? 'confirmed' : pending ? 'pending' : error ? 'error' : 'failed';

  return (
    <section className={`ceopro-subscription-result ${success ? 'is-success' : pending ? 'is-pending' : 'is-failed'}`}>
      <span className="ceopro-subscription-result__icon" aria-hidden="true"><Icon size={40} /></span>
      <h1>{t(`billing.result.${copyKey}.title`)}</h1>
      <p>{t(`billing.result.${copyKey}.description`)}</p>
      <div className="ceopro-subscription-result__actions">
        {!success && onBack && <Button variant="outline" onClick={onBack}>{t('billing.result.backToPlans')}</Button>}
        {(pending || error) && onRetry && <Button variant="outline" onClick={onRetry} loading={checking} loadingLabel={t('billing.result.checking')}>{t('billing.result.checkAgain')}</Button>}
        {onPrimary && <Button onClick={onPrimary} disabled={pending && checking}>{success ? t('billing.result.goToBilling') : t(`billing.result.${copyKey}.action`)}</Button>}
      </div>
    </section>
  );
}
