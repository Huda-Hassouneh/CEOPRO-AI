import FormError from './FormError.jsx';

export default function FormField({
  label,
  htmlFor,
  hint,
  error,
  errorId,
  children,
  className = '',
}) {
  return (
    <div className={`ceopro-input-wrapper ${className}`.trim()}>
      {label && <label className="ceopro-label" htmlFor={htmlFor}>{label}</label>}
      {children}
      {error ? <FormError id={errorId}>{error}</FormError> : null}
      {!error && hint ? <span className="ceopro-field-message ceopro-field-message--hint">{hint}</span> : null}
    </div>
  );
}
