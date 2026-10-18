
export default function Badge({ 
  children,
  variant = 'primary',
  className = '',
  ...props
}) {
  const getVariantStyles = () => {
    switch (variant) {
      case 'success':
        return { backgroundColor: 'var(--apex-success-bg)', color: 'var(--apex-success)' };
      case 'warning':
        return { backgroundColor: 'var(--apex-warning-bg)', color: 'var(--apex-warning)' };
      case 'error':
        return { backgroundColor: 'var(--apex-danger-bg)', color: 'var(--apex-danger)' };
      case 'light-success':
        return { backgroundColor: 'var(--apex-success-bg)', color: 'var(--apex-success)' };
      case 'neutral':
        return { backgroundColor: 'var(--apex-glass-strong)', color: 'var(--apex-text-2)' };
      case 'primary':
      default:
        return { backgroundColor: 'var(--apex-info-bg)', color: 'var(--apex-info)' };
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