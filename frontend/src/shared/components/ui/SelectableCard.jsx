import React from 'react';

export default function SelectableCard({
  type = 'radio',
  name,
  value,
  checked = false,
  onChange,
  title,
  description,
  icon,
  className = '',
  disabled = false,
}) {
  return (
    <label className={`ceopro-selectable-card ${checked ? 'is-selected' : ''} ${disabled ? 'is-disabled' : ''} ${className}`.trim()}>
      <input
        className="ceopro-selectable-card__control"
        type={type}
        name={name}
        value={value}
        checked={checked}
        disabled={disabled}
        onChange={onChange}
      />
      {icon && <span className="ceopro-selectable-card__icon" aria-hidden="true">{icon}</span>}
      <span className="ceopro-selectable-card__copy">
        <strong>{title}</strong>
        {description && <small>{description}</small>}
      </span>
      <span className="ceopro-selectable-card__indicator" aria-hidden="true">{checked ? '✓' : ''}</span>
    </label>
  );
}
