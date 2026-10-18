import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export default function IntegrationCard() {
  const { t: copyT } = useI18n();
  return <section className='panel'><h2>{copyT("interfaceCopy.integrationCard")}</h2></section>;
}
