import React, { useId, useRef } from 'react';
import FormError from '../forms/FormError.jsx';

export default function VerificationCodeInput({
  value = '',
  onChange,
  length = 6,
  disabled = false,
  ariaLabel = 'Verification code',
  error,
}) {
  const refs = useRef([]);
  const errorId = useId();

  const digits = Array.from({ length }, (_, index) => value[index] || '');

  const updateValue = (nextDigits) => {
    if (!onChange) return;
    onChange(nextDigits.join(''));
  };

  const handleChange = (event, index) => {
    const rawValue = event.target.value.replace(/\D/g, '').slice(-1);
    const nextDigits = [...digits];
    nextDigits[index] = rawValue;
    updateValue(nextDigits);

    if (rawValue && index < length - 1) {
      refs.current[index + 1]?.focus();
    }
  };

  const handleKeyDown = (event, index) => {
    if (event.key === 'Backspace' && !digits[index] && index > 0) {
      refs.current[index - 1]?.focus();
      return;
    }

    if (event.key === 'Backspace' && digits[index]) {
      const nextDigits = [...digits];
      nextDigits[index] = '';
      updateValue(nextDigits);
      return;
    }

    if (event.key === 'ArrowLeft' && index > 0) {
      refs.current[index - 1]?.focus();
    }

    if (event.key === 'ArrowRight' && index < length - 1) {
      refs.current[index + 1]?.focus();
    }
  };

  const handlePaste = (event) => {
    event.preventDefault();
    const pasted = (event.clipboardData.getData('text') || '').replace(/\D/g, '').slice(0, length);

    if (!pasted) return;

    const nextDigits = Array.from({ length }, (_, index) => pasted[index] || '');
    updateValue(nextDigits);
    const focusIndex = Math.min(pasted.length, length - 1);
    refs.current[focusIndex]?.focus();
  };

  return (
    <div>
      <div className="ceopro-verification-group" aria-label={ariaLabel} aria-invalid={Boolean(error)} aria-describedby={error ? errorId : undefined} role="group" dir="ltr">
        {Array.from({ length }, (_, index) => (
          <input
            key={index}
            ref={(node) => {
              refs.current[index] = node;
            }}
            className="ceopro-verification-input"
            type="text"
            inputMode="numeric"
            pattern="[0-9]*"
            name={`verification-code-${index + 1}`}
            autoComplete={index === 0 ? 'one-time-code' : 'off'}
            maxLength={1}
            value={digits[index] || ''}
            onChange={(event) => handleChange(event, index)}
            onKeyDown={(event) => handleKeyDown(event, index)}
            onPaste={handlePaste}
            disabled={disabled}
            aria-label={`${ariaLabel} ${index + 1}`}
          />
        ))}
      </div>
      <FormError id={errorId}>{error}</FormError>
    </div>
  );
}
