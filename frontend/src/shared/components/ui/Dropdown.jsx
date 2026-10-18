import React, { useState, useRef, useEffect, useId } from 'react';

export default function Dropdown({
  trigger,
  children,
  align = 'right',
  className = '',
  ...props
}) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef(null);
  const dropdownId = useId().replace(/:/g, '');

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsOpen(false);
      }
    };

    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, []);

  const menuStyle = {
    position: 'absolute',
    top: '100%',
    [align === 'right' ? 'right' : 'left']: 0,
    marginTop: 'var(--ceopro-space-2)',
    minWidth: '200px',
    backgroundColor: 'var(--ceopro-surface)',
    border: '1px solid var(--ceopro-border)',
    borderRadius: 'var(--ceopro-radius-md)',
    boxShadow: 'var(--ceopro-shadow-lg)',
    zIndex: 50,
    padding: 'var(--ceopro-space-2) 0',
    display: 'flex',
    flexDirection: 'column',
  };

  const toggleDropdown = () => setIsOpen(!isOpen);

  const triggerElement = React.isValidElement(trigger)
    ? React.cloneElement(trigger, {
        type: trigger.props.type || 'button',
        onClick: (event) => {
          if (trigger.props.onClick) trigger.props.onClick(event);
          toggleDropdown();
        },
        'aria-expanded': isOpen,
        'aria-haspopup': 'menu',
        'aria-controls': dropdownId,
      })
    : (
      <button type="button" onClick={toggleDropdown} aria-expanded={isOpen} aria-haspopup="menu" aria-controls={dropdownId}>
        {trigger}
      </button>
    );

  return (
    <div
      className={`ceopro-dropdown ${className}`.trim()}
      ref={dropdownRef}
      style={{ position: 'relative', display: 'inline-block' }}
      {...props}
    >
      {triggerElement}

      {isOpen && (
        <div id={dropdownId} className="ceopro-dropdown-menu" role="menu" style={menuStyle}>
          {React.Children.map(children, child => {
            if (React.isValidElement(child)) {
              return React.cloneElement(child, {
                onClick: (e) => {
                  if (child.props.onClick) {
                    child.props.onClick(e);
                  }
                  setIsOpen(false);
                },
                role: 'menuitem',
                tabIndex: 0,
                style: {
                  ...child.props.style,
                  padding: 'var(--ceopro-space-2) var(--ceopro-space-4)',
                  cursor: 'pointer',
                  color: 'var(--ceopro-text-primary)',
                  fontSize: '14px',
                  fontFamily: 'var(--ceopro-font-family)',
                  textDecoration: 'none',
                  display: 'block',
                  width: '100%',
                  textAlign: 'start',
                  background: 'transparent',
                  border: 'none',
                  transition: 'background 150ms ease',
                },
                onMouseEnter: (e) => e.target.style.background = 'var(--ceopro-surface-soft)',
                onMouseLeave: (e) => e.target.style.background = 'transparent',
              });
            }
            return child;
          })}
        </div>
      )}
    </div>
  );
}