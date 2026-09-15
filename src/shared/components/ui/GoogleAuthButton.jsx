import React from 'react';

export default function GoogleAuthButton({ children = 'Continue with Google', onClick, disabled = false, loading = false, loadingLabel = 'Loading...', type = 'button' }) {
  return (
    <button type={type} className="ceopro-google-button" onClick={onClick} disabled={disabled || loading} aria-busy={loading || undefined}>
      <svg className="ceopro-google-mark" viewBox="0 0 48 48" aria-hidden="true" focusable="false">
        <path fill="#EA4335" d="M24 9.5c3.54 0 6.72 1.22 9.22 3.6l6.85-6.85C35.64 2.29 30.27 0 24 0 14.64 0 6.64 5.38 2.58 13.22l7.98 6.2C12.18 13.73 17.62 9.5 24 9.5Z" />
        <path fill="#4285F4" d="M46.5 24.54c0-1.64-.15-3.2-.42-4.71H24v9h12.69c-.55 2.96-2.22 5.47-4.74 7.16l7.67 5.95C43.76 34.42 46.5 30.08 46.5 24.54Z" />
        <path fill="#FBBC05" d="M32.95 36.89c-2.06 1.38-4.71 2.2-8.95 2.2-6.46 0-11.9-4.35-13.85-10.19l-7.98 6.2C4.9 42.64 13.4 48 24 48c7.14 0 13.15-2.35 17.5-6.38l-8.55-4.73Z" />
        <path fill="#34A853" d="M11.15 28.9c-.52-1.55-.82-3.21-.82-4.9s.3-3.35.82-4.9l-7.98-6.2C1.79 15.08 1 18.86 1 24s.79 8.92 2.17 12.1l7.98-6.2Z" />
      </svg>
      <span>{loading ? loadingLabel : children}</span>
    </button>
  );
}
