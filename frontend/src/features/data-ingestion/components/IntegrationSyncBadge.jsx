import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function IntegrationSyncBadge() {
  const { t: copyT } = useI18n();
  return <span className="integration-sync-badge">{copyT("interfaceCopy.connected")}</span>;
}
