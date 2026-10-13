import { forwardRef, useId } from 'react';
import FormError from '../forms/FormError.jsx';

const Checkbox = forwardRef(({
  label,
  children,
  id,
  error,
  className = '',
  ...props
}, ref) => {
  const generatedId = useId().replace(/:/g, '');
  const inputId = id || `ceopro-checkbox-${generatedId}`;
  const errorId = `${inputId}-error`;

  return (
    <div className={`ceopro-checkbox-field ${className}`.trim()}>
      <label className="ceopro-auth-checkbox" htmlFor={inputId}>
        <input
          {...props}
          ref={ref}
          id={inputId}
          type="checkbox"
          aria-invalid={Boolean(error)}
          aria-describedby={error ? errorId : undefined}
        />
        <span>{children ?? label}</span>
      </label>
      <FormError id={errorId}>{error}</FormError>
    </div>
  );
});

Checkbox.displayName = 'Checkbox';
export default Checkbox;
