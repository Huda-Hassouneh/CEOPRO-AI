export default function FormError({ id, children, className = '' }) {
  if (!children) return null;

  return (
    <span
      id={id}
      className={`ceopro-field-message ceopro-field-message--error ${className}`.trim()}
      role="alert"
      aria-live="polite"
    >
      {children}
    </span>
  );
}
