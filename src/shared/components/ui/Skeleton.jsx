import React from 'react';

export default function Skeleton({ 
  width = '100%', 
  height = '20px', 
  variant = 'text', 
  className = '', 
  ...props 
}) {
  const getRadius = () => {
    if (variant === 'circular') return '50%';
    if (variant === 'rectangular') return 'var(--ceopro-radius-sm)';
    return '4px';
  };

  const skeletonStyle = {
    width,
    height,
    borderRadius: getRadius(),
    backgroundColor: 'var(--ceopro-border)',
    backgroundImage: 'linear-gradient(90deg, rgba(255, 255, 255, 0), rgba(255, 255, 255, 0.4), rgba(255, 255, 255, 0))',
    backgroundSize: '200px 100%',
    backgroundRepeat: 'no-repeat',
    display: 'inline-block',
    animation: 'ceopro-skeleton-pulse 1.2s ease-in-out infinite',
    ...props.style
  };

  return (
    <>
      <style>
        {`
          @keyframes ceopro-skeleton-pulse {
            0% { background-position: -200px 0; }
            100% { background-position: calc(200px + 100%) 0; }
          }
        `}
      </style>
      <div className={`ceopro-skeleton ${className}`.trim()} style={skeletonStyle} {...props} />
    </>
  );
}