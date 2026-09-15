import React, { useId, useState } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import Input from './Input.jsx';

export default function PasswordInput({
  label,
  id,
  error,
  hint,
  className = '',
  inputClassName = '',
  disabled = false,
  showPasswordLabel = 'Show password',
  hidePasswordLabel = 'Hide password',
  ...props
}) {
  const generatedId = useId();
  const inputId = id || `ceopro-password-${generatedId.replace(/:/g, '')}`;
  const [showPassword, setShowPassword] = useState(false);

  return (
    <Input
      id={inputId}
      label={label}
      error={error}
      hint={hint}
      className={className}
      inputClassName={inputClassName}
      disabled={disabled}
      type={showPassword ? 'text' : 'password'}
      rightIcon={
        <button
          type="button"
          className="ceopro-password-toggle"
          onClick={() => setShowPassword((current) => !current)}
          disabled={disabled}
          aria-label={showPassword ? hidePasswordLabel : showPasswordLabel}
          aria-pressed={showPassword}
        >
          {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
        </button>
      }
      {...props}
    />
  );
}
