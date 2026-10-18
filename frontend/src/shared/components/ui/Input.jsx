import React, { forwardRef, useId } from 'react';
import FormError from '../forms/FormError.jsx';

const Input = forwardRef(({
  label,
  error,
  hint,
  className = '',
  inputClassName = '',
  id,
  disabled = false,
  leftIcon,
  rightIcon,
  ...props
}, ref) => {
  const generatedId = useId();
  const fallbackId = `ceopro-input-${generatedId.replace(/:/g, '')}`;
  const inputId = id || fallbackId;
  const errorId = `${inputId}-error`;
  const hintId = `${inputId}-hint`;
  const describedBy = [error ? errorId : '', hint && !error ? hintId : ''].filter(Boolean).join(' ') || undefined;
  const hasIcon = Boolean(leftIcon || rightIcon);

  return (
    <div className={`ceopro-input-wrapper ${className}`.trim()}>
      {label && (
        <label htmlFor={inputId} className="ceopro-label">
          {label}
        </label>
      )}

      <div className={`ceopro-input-shell ${hasIcon ? 'ceopro-input-shell--with-icon' : ''} ${error ? 'ceopro-input-shell--error' : ''}`.trim()}>
        {leftIcon && <span className="ceopro-input-icon ceopro-input-icon--left" aria-hidden="true">{leftIcon}</span>}

        <input
          ref={ref}
          id={inputId}
          className={`ceopro-input ${inputClassName}`.trim()}
          disabled={disabled}
          aria-invalid={Boolean(error)}
          aria-describedby={describedBy}
          {...props}
        />

        {rightIcon && <span className="ceopro-input-icon ceopro-input-icon--right">{rightIcon}</span>}
      </div>

      <FormError id={errorId}>{error}</FormError>
      {hint && !error && (
        <span id={hintId} className="ceopro-field-message ceopro-field-message--hint">
          {hint}
        </span>
      )}
    </div>
  );
});

Input.displayName = 'Input';
export default Input;
