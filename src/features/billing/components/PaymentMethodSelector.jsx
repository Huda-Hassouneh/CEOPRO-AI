import { ArrowRight, CircleHelp, CreditCard } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { PAYMENT_PROVIDER_ASSETS } from '../../data-connections/config/providerAssets.js';

export function PaymentMethodSelector({ method, onMethodChange, onComplete, loading }) {
  const { t } = useI18n();

  return (
    <div className="ceopro-payment-method">
      <div className="ceopro-payment-tabs" role="radiogroup" aria-label={t('billing.payment.methodLabel')}>
        {['card', 'paypal', 'googlePay'].map((item) => (
          <button key={item} type="button" role="radio" aria-checked={method === item} className={method === item ? 'is-active' : ''} onClick={() => onMethodChange(item)}>
            {item === 'card' && <CreditCard size={16} aria-hidden="true" />}
            {item === 'paypal' && <img className="ceopro-payment-provider-logo" src={PAYMENT_PROVIDER_ASSETS.paypal} alt="" />}
            {item === 'googlePay' && <img className="ceopro-payment-provider-logo" src={PAYMENT_PROVIDER_ASSETS.googlePay} alt="" />}
            <span>{t(`billing.payment.methods.${item}`)}</span>
          </button>
        ))}
      </div>

      <div className="ceopro-payment-panel">
        {method === 'card' && (
          <div className="ceopro-card-fields">
            <label className="ceopro-payment-field"><span>{t('billing.payment.cardholder')}</span><input autoComplete="cc-name" placeholder={t('billing.payment.cardholderPlaceholder')} /></label>
            <label className="ceopro-payment-field"><span>{t('billing.payment.cardNumber')}</span><input inputMode="numeric" autoComplete="cc-number" placeholder="1234 5678 9012 3456" /></label>
            <div className="ceopro-payment-field-row">
              <label className="ceopro-payment-field"><span>{t('billing.payment.expiration')}</span><input inputMode="numeric" autoComplete="cc-exp" placeholder="MM / YY" /></label>
            <label className="ceopro-payment-field"><span>{t('billing.payment.cvv')} <CircleHelp size={12} aria-label={t('billing.payment.cvvHelp')} /></span><input inputMode="numeric" autoComplete="cc-csc" placeholder="123" /></label>
            </div>
            <Button fullWidth onClick={onComplete} loading={loading} loadingLabel={t('billing.payment.processing')} trailingIcon={<ArrowRight className="ceopro-setup-direction-icon" size={16} />}>{t('billing.payment.complete')}</Button>
          </div>
        )}
        {method === 'paypal' && (
          <div className="ceopro-provider-panel ceopro-paypal-panel">
            <img className="ceopro-provider-panel__logo ceopro-provider-panel__logo--paypal" src={PAYMENT_PROVIDER_ASSETS.paypal} alt="PayPal" />
            <Button className="ceopro-provider-button ceopro-provider-button--paypal" onClick={onComplete} loading={loading} trailingIcon={<ArrowRight className="ceopro-setup-direction-icon" size={16} />}>{t('billing.payment.continuePaypal')}</Button>
          </div>
        )}
        {method === 'googlePay' && (
          <div className="ceopro-provider-panel ceopro-google-pay-panel">
            <img className="ceopro-provider-panel__logo ceopro-provider-panel__logo--google" src={PAYMENT_PROVIDER_ASSETS.googlePay} alt="Google Pay" />
            <Button className="ceopro-provider-button ceopro-provider-button--google" onClick={onComplete} loading={loading} trailingIcon={<ArrowRight className="ceopro-setup-direction-icon" size={16} />}>{t('billing.payment.continueGooglePay')}</Button>
          </div>
        )}
      </div>

      <p className="ceopro-preview-notice" role="note">{t('billing.payment.previewNotice')}</p>
    </div>
  );
}
