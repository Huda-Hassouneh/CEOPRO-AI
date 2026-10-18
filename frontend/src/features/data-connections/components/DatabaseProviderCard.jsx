export function DatabaseProviderCard({ provider, title, description, icon, selected, onSelect }) {
  return (
    <button type="button" className={`ceopro-database-provider ${selected ? 'is-selected' : ''}`} onClick={() => onSelect(provider)} aria-pressed={selected}>
      <span className={`ceopro-database-provider__mark ceopro-database-provider__mark--${provider}`} aria-hidden="true"><img src={icon} alt="" /></span>
      <span><strong>{title}</strong><small>{description}</small></span>
      <b aria-hidden="true">›</b>
    </button>
  );
}
