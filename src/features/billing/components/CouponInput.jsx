import { useState } from 'react';
import Button from '../../../shared/components/ui/Button.jsx';
import Input from '../../../shared/components/ui/Input.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { useCoupon } from '../hooks/useCoupon.js';
import { getApiError } from '../api/billingApi.js';

export function CouponInput({ planId, value = '', onChange, onValidated, disabled = false }) {
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
      const response = await coupon.mutateAsync({ code, planId });
      const promo = response?.data ?? response;
      setMessage(
        promo?.discountType === 'percentage'
          ? t('billing.coupon.percentageApplied', { value: Number(promo.discountValue) })
          : t('billing.coupon.applied'),
      );
      onValidated?.(promo);
    } catch (requestError) {
      setError(getApiError(requestError).message || t('billing.coupon.invalid'));
      onValidated?.(null);
    }
  };

  return (
    <div className="billing-coupon-block">
      <div className="billing-coupon-row">
        <Input
          label={t('billing.coupon.label') || 'Promo code'}
          value={value}
          onChange={(event) => {
            onChange?.(event.target.value.toUpperCase());
            setMessage('');
            setError('');
            onValidated?.(null);
          }}
          disabled={disabled || coupon.isPending}
          error={error}
          placeholder={t('billing.coupon.placeholder') || 'Enter promo code'}
          autoComplete="off"
        />
        <Button
          type="button"
          variant="outline"
          onClick={applyCoupon}
          disabled={disabled || coupon.isPending || !value.trim() || !planId}
          loading={coupon.isPending}
        >
          {t('billing.coupon.apply') || 'Apply'}
        </Button>
      </div>
      {message && <p className="billing-coupon-success">{message}</p>}
    </div>
  );
}
