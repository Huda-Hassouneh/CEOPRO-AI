import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function StripeElementsField() {
  const { t: copyT } = useI18n();
  return <div className="stripe-elements-field">{copyT("interfaceCopy.stripeElements")}</div>;
}
