import CountUp from './CountUp.jsx';
import { AlertTriangle, ArrowDownRight, ArrowUpRight, ChevronLeft, ChevronRight, Inbox, Minus, RefreshCw } from 'lucide-react';

// The KEEL building blocks: every redesigned screen is composed of these so
// spacing, glass, typography and loading/empty/error states stay consistent.

export function Panel({ eyebrow, title, subtitle, actions, children, className = '', bodyClassName = '', as: Tag = 'section', ...rest }) {
  const hasHeader = eyebrow || title || subtitle || actions;
  return (
    <Tag className={`apex-panel ${className}`.trim()} {...rest}>
      {hasHeader && (
        <header className="apex-panel__header">
          <div className="apex-panel__titles">
            {eyebrow && <p className="apex-eyebrow">{eyebrow}</p>}
            {title && <h2 className="apex-panel__title">{title}</h2>}
            {subtitle && <p className="apex-panel__subtitle">{subtitle}</p>}
          </div>
          {actions && <div className="apex-panel__actions">{actions}</div>}
        </header>
      )}
      <div className={`apex-panel__body ${bodyClassName}`.trim()}>{children}</div>
    </Tag>
  );
}

export function Stat({ label, value, hint, delta, deltaLabel, icon: Icon, tone = 'accent', className = '' }) {
  return (
    <div className={`apex-stat apex-stat--${tone} ${className}`.trim()}>
      <div className="apex-stat__top">
        <span className="apex-stat__label">{label}</span>
        {Icon && <span className="apex-stat__icon" aria-hidden="true"><Icon size={16} /></span>}
      </div>
      <strong className="apex-stat__value apex-num"><CountUp value={value} /></strong>
      {(delta != null || hint) && (
        <div className="apex-stat__foot">
          {delta != null && <Delta value={delta} label={deltaLabel} />}
          {hint && <span className="apex-stat__hint">{hint}</span>}
        </div>
      )}
    </div>
  );
}

export function Delta({ value, label, invert = false, suffix = '%' }) {
  if (value == null || Number.isNaN(Number(value))) return null;
  const n = Number(value);
  const good = invert ? n < 0 : n > 0;
  const tone = Math.abs(n) < 0.05 ? 'flat' : good ? 'up' : 'down';
  const Icon = tone === 'flat' ? Minus : n > 0 ? ArrowUpRight : ArrowDownRight;
  return (
    <span className={`apex-delta apex-delta--${tone}`}>
      <Icon size={13} aria-hidden="true" />
      <span className="apex-num" dir="ltr">{n > 0 ? '+' : ''}{n.toFixed(Math.abs(n) >= 10 ? 0 : 1)}{suffix}</span>
      {label && <span className="apex-delta__label">{label}</span>}
    </span>
  );
}

export function Pill({ tone = 'neutral', children, icon: Icon, className = '' }) {
  return <span className={`apex-pill apex-pill--${tone} ${className}`.trim()}>{Icon && <Icon size={12} aria-hidden="true" />}{children}</span>;
}

export function StateBlock({ kind = 'empty', title, description, action, onRetry, retryLabel, compact = false }) {
  if (kind === 'loading') {
    return (
      <div className={`apex-state apex-state--loading${compact ? ' is-compact' : ''}`} role="status" aria-live="polite">
        <div className="apex-skeleton" style={{ width: '42%' }} />
        <div className="apex-skeleton" style={{ width: '88%' }} />
        <div className="apex-skeleton" style={{ width: '64%' }} />
        {title && <span className="sr-only">{title}</span>}
      </div>
    );
  }
  const Icon = kind === 'error' ? AlertTriangle : Inbox;
  return (
    <div className={`apex-state apex-state--${kind}${compact ? ' is-compact' : ''}`} role={kind === 'error' ? 'alert' : undefined}>
      <span className="apex-state__icon" aria-hidden="true"><Icon size={20} /></span>
      {title && <p className="apex-state__title">{title}</p>}
      {description && <p className="apex-state__description">{description}</p>}
      {(action || onRetry) && (
        <div className="apex-state__actions">
          {onRetry && <button type="button" className="apex-btn apex-btn--ghost" onClick={onRetry}><RefreshCw size={14} aria-hidden="true" />{retryLabel}</button>}
          {action}
        </div>
      )}
    </div>
  );
}

export function Meter({ value, max = 100, tone = 'accent', label }) {
  const pct = max > 0 ? Math.max(0, Math.min(100, (Number(value) / max) * 100)) : 0;
  return (
    <div className={`apex-meter apex-meter--${tone}`} role="meter" aria-valuemin={0} aria-valuemax={max} aria-valuenow={Number(value) || 0} aria-label={label}>
      <span style={{ width: `${pct}%` }} />
    </div>
  );
}

export function ApexButton({ variant = 'primary', size = 'md', icon: Icon, children, loading = false, className = '', ...rest }) {
  return (
    <button type="button" className={`apex-btn apex-btn--${variant} apex-btn--${size} ${className}`.trim()} disabled={loading || rest.disabled} aria-busy={loading || undefined} {...rest}>
      {loading ? <span className="apex-spinner" aria-hidden="true" /> : Icon && <Icon size={size === 'sm' ? 14 : 16} aria-hidden="true" />}
      {children && <span>{children}</span>}
    </button>
  );
}

// Previous/next paging for a list of `total` rows shown `pageSize` at a time.
// Renders nothing when everything fits on one page.
export function Pager({ page, pageSize, total, onChange, t, dir, number, busy = false }) {
  if (total <= pageSize) return null;
  const pages = Math.ceil(total / pageSize);
  const fmt = (value) => (number ? number.format(value) : String(value));
  return (
    <div className="apex-pager">
      <span className="apex-muted">{t('productsApex.pageOf', { from: fmt(page * pageSize + 1), to: fmt(Math.min(total, (page + 1) * pageSize)), total: fmt(total) })}</span>
      <div>
        <ApexButton size="sm" variant="secondary" icon={dir === 'rtl' ? ChevronRight : ChevronLeft} disabled={page === 0 || busy} onClick={() => onChange(page - 1)}>{t('productsApex.previous')}</ApexButton>
        <ApexButton size="sm" variant="secondary" disabled={page + 1 >= pages || busy} onClick={() => onChange(page + 1)}>{t('productsApex.next')}{dir === 'rtl' ? <ChevronLeft size={14} /> : <ChevronRight size={14} />}</ApexButton>
      </div>
    </div>
  );
}
