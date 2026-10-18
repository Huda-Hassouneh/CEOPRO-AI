import React from 'react';

export default function Button({
  children,
  variant = 'primary',
  className = '',
  loading = false,
  loadingLabel = 'Loading...',
  disabled = false,
  type = 'button',
  onClick,
  fullWidth = false,
  size = 'md',
  leadingIcon,
  trailingIcon,
  ...props
}) {
  const baseClass = 'ceopro-button';
  const variantClass = {
    primary: 'ceopro-button--primary',
    secondary: 'ceopro-button--secondary',
    outline: 'ceopro-button--outline',
    ghost: 'ceopro-button--ghost',
  }[variant] || 'ceopro-button--primary';

  const sizeClass = size === 'sm' ? 'ceopro-button--sm' : size === 'lg' ? 'ceopro-button--lg' : 'ceopro-button--md';
  const combinedClasses = `${baseClass} ${variantClass} ${sizeClass} ${fullWidth ? 'ceopro-button--full-width' : ''} ${className}`.trim();
  const isDisabled = disabled || loading;

  const handleClick = (event) => {
    if (loading || disabled) {
      event.preventDefault();
      event.stopPropagation();
      return;
    }

    if (onClick) {
      onClick(event);
    }
  };

  return (
    <button
      type={type}
      className={combinedClasses}
      disabled={isDisabled}
      aria-busy={loading || undefined}
      data-loading={loading ? 'true' : undefined}
      onClick={handleClick}
      {...props}
    >
      {loading ? <span className="ceopro-button__content" aria-label={loadingLabel}>{loadingLabel}</span> : (
        <span className="ceopro-button__content">
          {leadingIcon && <span className="ceopro-button__icon ceopro-button__icon--leading">{leadingIcon}</span>}
          <span>{children}</span>
          {trailingIcon && <span className="ceopro-button__icon ceopro-button__icon--trailing">{trailingIcon}</span>}
        </span>
      )}
    </button>
  );
}
