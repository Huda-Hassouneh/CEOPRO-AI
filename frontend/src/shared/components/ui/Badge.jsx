import React from 'react';

export default function Badge({ 
  children,
  variant = 'primary',
  className = '',
  ...props
}) {
  const getVariantStyles = () => {
    switch (variant) {
      case 'success':
        return { backgroundColor: 'var(--ceopro-success)', color: 'var(--ceopro-surface)' };
      case 'warning':
        return { backgroundColor: 'var(--ceopro-warning)', color: 'var(--ceopro-surface)' };
      case 'error':
        return { backgroundColor: 'var(--ceopro-error)', color: 'var(--ceopro-surface)' };
      case 'light-success':
        return { backgroundColor: '#d1fae5', color: '#065f46' };
      case 'neutral':
        return { backgroundColor: 'var(--ceopro-surface-soft)', color: 'var(--ceopro-text-secondary)' };
      case 'primary':
      default:
        return { backgroundColor: 'var(--ceopro-primary)', color: 'var(--ceopro-surface)' };
    }
  };

  const baseStyle = {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '4px 10px',
    fontSize: '11px',
    fontWeight: '700',
    borderRadius: '9999px',
    fontFamily: 'var(--ceopro-font-family)',
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
    whiteSpace: 'nowrap',
    ...getVariantStyles(),
    ...props.style
  };

  return (
    <span className={`ceopro-badge ${className}`.trim()} style={baseStyle} {...props}>
      {children}
    </span>
  );
}