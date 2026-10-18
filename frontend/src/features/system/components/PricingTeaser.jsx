import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export default function PricingTeaser() {
  const { t: copyT } = useI18n();
  return <section className='price-card'><h2>{copyT("interfaceCopy.pricing")}</h2></section>;
}
