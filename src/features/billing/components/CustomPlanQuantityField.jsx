import { useId, useState } from 'react';

export function CustomPlanQuantityField({ label, description, value, min, max, onChange, formatValue, icon }) {
  const id = useId();
  const [draft, setDraft] = useState(null);
  const commit = () => {
    if (draft !== null && draft !== '') {
      onChange(Math.min(max, Math.max(min, Number(draft))));
    }
    setDraft(null);
  };

  return (
    <div className="ceopro-range-field ceopro-custom-quantity">
      <div className="ceopro-range-field__header">
        <span className="ceopro-range-field__icon" aria-hidden="true">{icon}</span>
        <span className="ceopro-range-field__copy">
          <label htmlFor={id}>{label}</label>
          <small id={`${id}-description`}>{description}</small>
        </span>
      </div>
      <input
        id={id}
        type="text"
        inputMode="numeric"
        pattern="[0-9]*"
        dir="ltr"
        value={draft ?? String(value)}
        aria-describedby={`${id}-description ${id}-bounds`}
        aria-invalid={draft !== null && draft !== '' && (Number(draft) < min || Number(draft) > max)}
        onChange={(event) => {
          const next = event.target.value.replace(/[٠-٩۰-۹]/g, (digit) => String(digit.charCodeAt(0) - (digit <= '٩' ? 1632 : 1776)));
          if (!/^\d*$/.test(next)) return;
          setDraft(next);
          if (next !== '' && Number(next) >= min && Number(next) <= max) onChange(Number(next));
        }}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === 'Enter') { event.preventDefault(); commit(); }
          if (event.key === 'Escape') setDraft(null);
        }}
      />
      <div id={`${id}-bounds`} className="ceopro-range-field__bounds">
        <span>{formatValue(min)} – {formatValue(max)}</span>
      </div>
    </div>
  );
}
