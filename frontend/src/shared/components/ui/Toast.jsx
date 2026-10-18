
export default function Toast({ 
  message,
  variant = 'success',
  onClose,
  className = '',
  ...props
}) {
  const getVariantStyles = () => {
    switch (variant) {
      case 'error':
        return { backgroundColor: 'var(--apex-glass-solid)', color: 'var(--apex-text)', borderInlineStart: '4px solid var(--apex-danger)' };
      case 'warning':
        return { backgroundColor: 'var(--apex-glass-solid)', color: 'var(--apex-text)', borderInlineStart: '4px solid var(--apex-warning)' };
      case 'info':
        return { backgroundColor: 'var(--apex-glass-solid)', color: 'var(--apex-text)', borderInlineStart: '4px solid var(--apex-info)' };
      case 'success':
      default:
        return { backgroundColor: 'var(--apex-glass-solid)', color: 'var(--apex-text)', borderInlineStart: '4px solid var(--apex-success)' };
    }
  };

  const toastStyle = {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: 'var(--ceopro-space-3) var(--ceopro-space-4)',
    borderRadius: 'var(--ceopro-radius-sm)',
    boxShadow: 'var(--apex-glass-highlight), var(--apex-shadow-hover)',
    backdropFilter: 'var(--apex-blur)',
    border: '1px solid var(--apex-glass-border-strong)',
    animation: 'apex-pop 320ms var(--apex-ease) both',
    fontFamily: 'var(--ceopro-font-family)',
    fontSize: '14px',
    fontWeight: '500',
    minWidth: '280px',
    maxWidth: '400px',
    ...getVariantStyles(),
    ...props.style
  };

  const toastRole = variant === 'error' ? 'alert' : 'status';

  return (
    <div className={`ceopro-toast ${className}`.trim()} style={toastStyle} role={toastRole} aria-live={variant === 'error' ? 'assertive' : 'polite'} aria-atomic="true" {...props}>
      <span>{message}</span>
      {onClose && (
        <button
          type="button"
          onClick={onClose}
          aria-label="Dismiss notification"
          style={{ background: 'transparent', border: 'none', color: 'inherit', cursor: 'pointer', fontSize: '16px', marginInlineStart: 'var(--ceopro-space-3)', padding: 0 }}
        >
          &times;
        </button>
      )}
    </div>
  );
}