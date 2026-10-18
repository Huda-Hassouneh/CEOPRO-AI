import React from 'react';

export default function Card({ 
  children, 
  className = '', 
  interactive = false,
  onClick,
  ...props 
}) {
  const baseClass = 'ceopro-card';
  const combinedClasses = `${baseClass} ${className}`.trim();

  const interactiveStyles = interactive || onClick ? {
    cursor: 'pointer',
    transition: 'border-color 150ms ease, box-shadow 150ms ease, transform 150ms ease'
  } : {};

  return (
    <div 
      className={combinedClasses} 
      onClick={onClick}
      style={{ ...interactiveStyles, ...props.style }}
      {...props}
    >
      {children}
    </div>
  );
}