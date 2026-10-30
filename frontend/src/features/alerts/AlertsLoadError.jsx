export function AlertsLoadError({ onRetry, busy, t }) {
  return (
    <div className="apex-alerts__error" aria-busy={busy}>
      <p className="apex-alerts__empty" role="alert">{t('alerts.error')}</p>
      <button type="button" className="apex-btn apex-btn--ghost apex-btn--sm" onClick={onRetry} disabled={busy}>
        {busy ? t('common.loading') : t('alerts.retry')}
      </button>
    </div>
  );
}
