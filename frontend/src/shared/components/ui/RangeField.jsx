import React, { useId } from 'react';

export default function RangeField({
  label,
  description,
  value,
  min,
  max,
  step = 1,
  onChange,
  formatValue = (nextValue) => String(nextValue),
  icon,
}) {
  const id = useId().replace(/:/g, '');
  const outputId = `${id}-value`;

  return (
    <div className="ceopro-range-field">
      <div className="ceopro-range-field__header">
        {icon && <span className="ceopro-range-field__icon" aria-hidden="true">{icon}</span>}
        <span className="ceopro-range-field__copy">
          <label htmlFor={id}>{label}</label>
          {description && <small>{description}</small>}
        </span>
        <output id={outputId} htmlFor={id}>{formatValue(value)}</output>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        aria-describedby={outputId}
        onChange={(event) => onChange?.(Number(event.target.value))}
      />
      <div className="ceopro-range-field__bounds" aria-hidden="true">
        <span>{formatValue(min)}</span>
        <span>{formatValue(max)}</span>
      </div>
    </div>
  );
}
