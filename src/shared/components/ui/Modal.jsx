import React, { useEffect, useId, useRef } from 'react';
import { createPortal } from 'react-dom';

export default function Modal({ 
  isOpen,
  onClose,
  title,
  closeLabel,
  children,
  footer,
  maxWidth = '500px',
  className = '',
  ...props 
}) {
  const modalRef = useRef(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const closeButtonRef = useRef(null);
  const titleId = useId().replace(/:/g, '');
  const bodyId = useId().replace(/:/g, '');

  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = 'unset';
    }

    return () => {
      document.body.style.overflow = 'unset';
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;

    const trigger = document.activeElement;

    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        onCloseRef.current?.();
      }
      if (event.key === 'Tab') {
        const controls = [...modalRef.current.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex="0"]')].filter((element) => element.getClientRects().length);
        const first = controls[0];
        const last = controls[controls.length - 1];
        if (event.shiftKey && (document.activeElement === first || !modalRef.current.contains(document.activeElement))) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      if (trigger?.isConnected) trigger.focus();
    };
  }, [isOpen]);

  useEffect(() => {
    if (isOpen && closeButtonRef.current) {
      closeButtonRef.current.focus();
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const overlayStyle = {
    position: 'fixed',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(27, 27, 36, 0.6)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 9999,
    padding: 'var(--ceopro-space-4)'
  };

  const modalStyle = {
    background: 'var(--ceopro-surface)',
    borderRadius: 'var(--ceopro-radius-md)',
    boxShadow: 'var(--ceopro-shadow-lg)',
    width: '100%',
    maxWidth: maxWidth,
    maxHeight: '90vh',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
    ...props.style
  };

  const headerStyle = {
    padding: 'var(--ceopro-space-4) var(--ceopro-space-5)',
    borderBottom: '1px solid var(--ceopro-border-soft)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between'
  };

  const titleStyle = {
    margin: 0,
    fontSize: '18px',
    fontWeight: '700',
    color: 'var(--ceopro-text-primary)'
  };

  const closeBtnStyle = {
    background: 'transparent',
    border: 'none',
    fontSize: '24px',
    lineHeight: 1,
    color: 'var(--ceopro-text-muted)',
    cursor: 'pointer',
    padding: 0,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    transition: 'color 150ms ease'
  };

  const bodyStyle = {
    padding: 'var(--ceopro-space-5)',
    overflowY: 'auto'
  };

  const footerStyle = {
    padding: 'var(--ceopro-space-4) var(--ceopro-space-5)',
    borderTop: '1px solid var(--ceopro-border-soft)',
    display: 'flex',
    justifyContent: 'flex-end',
    gap: 'var(--ceopro-space-3)',
    backgroundColor: 'var(--ceopro-surface-soft)'
  };

  return createPortal(
    <div className="ceopro-modal-overlay" style={overlayStyle} onClick={onClose}>
      <div
        ref={modalRef}
        className={`ceopro-modal ${className}`.trim()}
        style={modalStyle}
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? `${titleId}` : undefined}
        aria-describedby={bodyId}
        {...props}
      >
        <div style={headerStyle}>
          {title && <h2 id={titleId} style={titleStyle}>{title}</h2>}
          <button
            ref={closeButtonRef}
            style={closeBtnStyle}
            onClick={onClose}
            aria-label={closeLabel || title}
            onMouseEnter={e => e.target.style.color = 'var(--ceopro-text-primary)'}
            onMouseLeave={e => e.target.style.color = 'var(--ceopro-text-muted)'}
          >
            &times;
          </button>
        </div>
        <div id={bodyId} style={bodyStyle}>
          {children}
        </div>
        {footer && (
          <div style={footerStyle}>
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body
  );
}
