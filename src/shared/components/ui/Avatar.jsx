import React, { useState } from 'react';

export default function Avatar({ 
  src, 
  alt = 'Avatar', 
  fallback,
  size = '40px',
  className = '', 
  ...props 
}) {
  const [imgError, setImgError] = useState(false);
  
  const avatarStyle = {
    width: size,
    height: size,
    borderRadius: '50%',
    overflow: 'hidden',
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'var(--ceopro-primary-light)',
    color: 'var(--ceopro-primary)',
    fontFamily: 'var(--ceopro-font-family)',
    fontWeight: '600',
    fontSize: `calc(${size} / 2.5)`,
    flexShrink: 0,
    border: '1px solid var(--ceopro-border-soft)',
    ...props.style
  };

  const imgStyle = {
    width: '100%',
    height: '100%',
    objectFit: 'cover'
  };

  return (
    <div className={`ceopro-avatar ${className}`.trim()} style={avatarStyle} {...props}>
      {src && !imgError ? (
        <img 
          src={src} 
          alt={alt} 
          style={imgStyle}
          onError={() => setImgError(true)}
        />
      ) : (
        <span className="ceopro-avatar-fallback">
          {fallback || (alt ? alt.charAt(0).toUpperCase() : '')}
        </span>
      )}
    </div>
  );
}