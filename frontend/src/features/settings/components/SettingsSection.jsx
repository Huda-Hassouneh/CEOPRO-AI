export function SettingsSection({ title, subtitle, actions, children, className = '' }) {
  return <section className={`settings-section-card ${className}`.trim()}><header><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{actions && <div>{actions}</div>}</header><div className="settings-section-card__body">{children}</div></section>;
}
