import React from 'react';

export default function SegmentedControl({ name, value, options = [], onChange, ariaLabel, className = '' }) {
  return (
    <fieldset className={`ceopro-segmented-control ${className}`.trim()} aria-label={ariaLabel}>
      <legend className="ceopro-visually-hidden">{ariaLabel}</legend>
      {options.map((option) => (
        <label className={`ceopro-segmented-control__option ${value === option.value ? 'is-selected' : ''}`} key={option.value}>
          <input
            type="radio"
            name={name}
            value={option.value}
            checked={value === option.value}
            onChange={() => onChange?.(option.value)}
          />
          <span>{option.label}</span>
          {option.badge && <small>{option.badge}</small>}
        </label>
      ))}
    </fieldset>
  );
}
