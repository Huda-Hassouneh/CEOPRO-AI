import React from 'react';

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
        return { backgroundColor: 'var(--ceopro-error)', color: 'var(--ceopro-surface)' };
      case 'warning':
        return { backgroundColor: 'var(--ceopro-warning)', color: 'var(--ceopro-surface)' };
      case 'info':
        return { backgroundColor: 'var(--ceopro-info)', color: 'var(--ceopro-surface)' };
      case 'success':
      default:
        return { backgroundColor: 'var(--ceopro-success)', color: 'var(--ceopro-surface)' };
    }
  };

  const toastStyle = {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: 'var(--ceopro-space-3) var(--ceopro-space-4)',
    borderRadius: 'var(--ceopro-radius-sm)',
    boxShadow: 'var(--ceopro-shadow-lg)',
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