import React, { forwardRef, useId } from 'react';

const Select = forwardRef(({ 
  label,
  error,
  hint,
  options = [],
  className = '',
  id,
  disabled = false,
  ...props 
}, ref) => {
  const generatedId = useId();
  const fallbackId = `ceopro-select-${generatedId.replace(/:/g, '')}`;
  const selectId = id || fallbackId;
  const errorId = `${selectId}-error`;
  const hintId = `${selectId}-hint`;
  const describedBy = [error ? errorId : '', hint && !error ? hintId : ''].filter(Boolean).join(' ') || undefined;

  const selectStyle = {
    width: '100%',
    minHeight: '44px',
    padding: 'var(--ceopro-space-2) var(--ceopro-space-3)',
    border: `1px solid ${error ? 'var(--ceopro-error)' : 'var(--ceopro-border)'}`,
    borderRadius: 'var(--ceopro-radius-sm)',
    background: 'var(--ceopro-surface)',
    color: 'var(--ceopro-text-primary)',
    fontFamily: 'var(--ceopro-font-family)',
    fontSize: '14px',
    outline: 'none',
    boxShadow: error ? '0 0 0 3px rgba(239, 68, 68, 0.1)' : undefined,
    transition: 'border-color 150ms ease, box-shadow 150ms ease'
  };

  return (
    <div className={`ceopro-select-wrapper ${className}`.trim()} style={{ marginBottom: 'var(--ceopro-space-4)' }}>
      {label && (
        <label htmlFor={selectId} className="ceopro-label">
          {label}
        </label>
      )}
      <select
        ref={ref}
        id={selectId}
        disabled={disabled}
        aria-invalid={Boolean(error)}
        aria-describedby={describedBy}
        style={selectStyle}
        {...props}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      {error && (
        <span id={errorId} style={{ display: 'block', color: 'var(--ceopro-error)', fontSize: '12px', marginTop: 'var(--ceopro-space-1)', fontWeight: '500' }}>
          {error}
        </span>
      )}
      {hint && !error && (
        <span id={hintId} style={{ display: 'block', color: 'var(--ceopro-text-muted)', fontSize: '12px', marginTop: 'var(--ceopro-space-1)' }}>
          {hint}
        </span>
      )}
    </div>
  );
});

Select.displayName = 'Select';
export default Select;