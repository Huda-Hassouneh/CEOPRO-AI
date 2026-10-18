import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export default function SettingsSecurityPage() {
  const { t: copyT } = useI18n();
  return <section className='page'><h1>{copyT("interfaceCopy.securitySettings")}</h1></section>;
}
