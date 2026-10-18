import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function CheckoutForm() {
  const { t: copyT } = useI18n();
  return <div className="checkout-form">{copyT("interfaceCopy.checkout")}</div>;
}
