import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function SessionSidebar() {
  const { t: copyT } = useI18n();
  return <aside className="session-sidebar">{copyT("interfaceCopy.sessions")}</aside>;
}
