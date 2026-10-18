import { useI18n } from '../providers/I18nProvider.jsx';
export function SettingsLayout({ children }) {
  const { t: copyT } = useI18n();
  return (
    <div className="settings-layout">
      <aside className="settings-sidebar">
        <span>{copyT("interfaceCopy.profile")}</span>
        <span>{copyT("interfaceCopy.security")}</span>
        <span>{copyT("interfaceCopy.integrations")}</span>
        <span>{copyT("interfaceCopy.team")}</span>
      </aside>
      <main className="settings-content">{children}</main>
    </div>
  );
}
