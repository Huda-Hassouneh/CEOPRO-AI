import React from 'react';

export default function EmptyState({ 
  title, 
  description, 
  icon, 
  action, 
  className = '', 
  ...props 
}) {
  const containerStyle = {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 'var(--ceopro-space-8)',
    textAlign: 'center',
    background: 'var(--ceopro-surface)',
    borderRadius: 'var(--ceopro-radius-md)',
    border: '1px dashed var(--ceopro-border)',
    ...props.style
  };

  const iconStyle = {
    marginBottom: 'var(--ceopro-space-4)',
    color: 'var(--ceopro-primary)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: '64px',
    height: '64px',
    backgroundColor: 'var(--ceopro-primary-light)',
    borderRadius: '50%'
  };

  const titleStyle = {
    fontSize: '18px',
    fontWeight: '700',
    color: 'var(--ceopro-text-primary)',
    margin: '0 0 var(--ceopro-space-2) 0'
  };

  const descStyle = {
    fontSize: '14px',
    color: 'var(--ceopro-text-secondary)',
    margin: '0 0 var(--ceopro-space-6) 0',
    maxWidth: '400px',
    lineHeight: '1.5'
  };

  return (
    <div className={`ceopro-empty-state ${className}`.trim()} style={containerStyle} {...props}>
      {icon && <div style={iconStyle}>{icon}</div>}
      {title && <h3 style={titleStyle}>{title}</h3>}
      {description && <p style={descStyle}>{description}</p>}
      {action && <div>{action}</div>}
    </div>
  );
}