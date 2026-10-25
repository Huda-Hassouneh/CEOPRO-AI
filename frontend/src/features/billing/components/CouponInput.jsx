import { useState } from 'react';
import Button from '../../../shared/components/ui/Button.jsx';
import Input from '../../../shared/components/ui/Input.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { useCoupon } from '../hooks/useCoupon.js';
import { getApiError } from '../api/customerBillingApi.js';

export function CouponInput({ planId, billingPeriod, value = '', onChange, onValidated, disabled = false }) {
  const { t } = useI18n();
  const coupon = useCoupon();
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const applyCoupon = async () => {
    const code = value.trim();
    if (!code || !planId) return;

    setMessage('');
    setError('');
    try {
      const response = await coupon.mutateAsync({ code, planId, billingPeriod });
      const promo = response?.data ?? response;
      setMessage(
        promo?.discountType === 'percentage'
          ? t('billing.coupon.percentageApplied', { value: Number(promo.discountValue) })
          : t('billing.coupon.applied'),
      );
      onValidated?.(promo);
    } catch (requestError) {
      const reason = getApiError(requestError).code;
      const key = `billing.promotionErrors.${reason}`;
      setError(t(key) === key ? t('billing.coupon.invalid') : t(key));
      onValidated?.(null);
    }
  };

  return (
    <div className="billing-coupon-block">
      <div className="billing-coupon-row">
        <Input
          label={t('billing.coupon.label')}
          value={value}
          onChange={(event) => {
            onChange?.(event.target.value.toUpperCase());
            setMessage('');
            setError('');
            onValidated?.(null);
          }}
          disabled={disabled || coupon.isPending}
          error={error}
          placeholder={t('billing.coupon.placeholder')}
          autoComplete="off"
        />
        <Button
          type="button"
          variant="outline"
          onClick={applyCoupon}
          disabled={disabled || coupon.isPending || !value.trim() || !planId}
          loading={coupon.isPending}
        >
          {t('billing.coupon.apply')}
        </Button>
      </div>
      {message && <p className="billing-coupon-success">{message}</p>}
    </div>
  );
}
