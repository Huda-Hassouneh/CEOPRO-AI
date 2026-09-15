export function SettingsLayout({ children }) {
  return (
    <div className="settings-layout">
      <aside className="settings-sidebar">
        <span>Profile</span>
        <span>Security</span>
        <span>Integrations</span>
        <span>Team</span>
      </aside>
      <main className="settings-content">{children}</main>
    </div>
  );
}
