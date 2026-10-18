import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export default function SettingsTeamManagementPage() {
  const { t: copyT } = useI18n();
  return <section className='page'><h1>{copyT("interfaceCopy.teamManagement")}</h1></section>;
}
