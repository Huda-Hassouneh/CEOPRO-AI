import { AlertCircle, CircleCheck } from 'lucide-react';

export function AuthStatusMessage({ children, tone = 'error', className = '' }) {
  if (!children) return null;
  const isSuccess = tone === 'success';

  return (
    <div
      className={`ceopro-auth-status ceopro-auth-status--${tone} ${className}`.trim()}
      role={isSuccess ? 'status' : 'alert'}
      aria-live={isSuccess ? 'polite' : 'assertive'}
    >
      {isSuccess
        ? <CircleCheck size={18} aria-hidden="true" />
        : <AlertCircle size={18} aria-hidden="true" />}
      <span>{children}</span>
    </div>
  );
}
