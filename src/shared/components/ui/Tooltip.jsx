import React, { useState, useId } from 'react';

export default function Tooltip({
  content,
  children,
  position = 'top',
  className = '',
  ...props
}) {
  const [isVisible, setIsVisible] = useState(false);
  const tooltipId = useId().replace(/:/g, '');

  const containerStyle = {
    position: 'relative',
    display: 'inline-block',
  };

  const getPositionStyles = () => {
    switch (position) {
      case 'bottom':
        return { top: '100%', left: '50%', transform: 'translateX(-50%)', marginTop: '6px' };
      case 'left':
        return { right: '100%', top: '50%', transform: 'translateY(-50%)', marginRight: '6px' };
      case 'right':
        return { left: '100%', top: '50%', transform: 'translateY(-50%)', marginLeft: '6px' };
      case 'top':
      default:
        return { bottom: '100%', left: '50%', transform: 'translateX(-50%)', marginBottom: '6px' };
    }
  };

  const tooltipStyle = {
    position: 'absolute',
    backgroundColor: 'var(--ceopro-text-primary)',
    color: 'var(--ceopro-surface)',
    padding: '4px 8px',
    borderRadius: '4px',
    fontSize: '12px',
    fontFamily: 'var(--ceopro-font-family)',
    whiteSpace: 'nowrap',
    zIndex: 1000,
    pointerEvents: 'none',
    boxShadow: 'var(--ceopro-shadow-sm)',
    ...getPositionStyles(),
  };

  const trigger = React.isValidElement(children)
    ? React.cloneElement(children, {
        tabIndex: 0,
        'aria-describedby': tooltipId,
        onFocus: (event) => {
          children.props?.onFocus?.(event);
          setIsVisible(true);
        },
        onBlur: (event) => {
          children.props?.onBlur?.(event);
          setIsVisible(false);
        },
        onMouseEnter: (event) => {
          children.props?.onMouseEnter?.(event);
          setIsVisible(true);
        },
        onMouseLeave: (event) => {
          children.props?.onMouseLeave?.(event);
          setIsVisible(false);
        },
      })
    : <span tabIndex={0} aria-describedby={tooltipId} onFocus={() => setIsVisible(true)} onBlur={() => setIsVisible(false)} onMouseEnter={() => setIsVisible(true)} onMouseLeave={() => setIsVisible(false)}>{children}</span>;

  return (
    <div
      className={`ceopro-tooltip-wrapper ${className}`.trim()}
      style={containerStyle}
      {...props}
    >
      {trigger}
      {isVisible && (
        <div id={tooltipId} role="tooltip" style={tooltipStyle}>
          {content}
        </div>
      )}
    </div>
  );
}