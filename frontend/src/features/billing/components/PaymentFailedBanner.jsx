import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function PaymentFailedBanner() {
  const { t: copyT } = useI18n();
  return <div className="payment-failed-banner">{copyT("interfaceCopy.paymentFailed")}</div>;
}
