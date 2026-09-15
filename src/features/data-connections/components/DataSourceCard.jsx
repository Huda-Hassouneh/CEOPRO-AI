import Button from '../../../shared/components/ui/Button.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';

export function DataSourceCard({ icon, iconSrc, title, description, actionLabel, onAction, status = 'not-connected', error = '', loading = false, actionDisabled = false, showStatus = true, children }) {
  const { t } = useI18n();

  return (
    <article className="ceopro-data-source-card">
      <span className="ceopro-data-source-card__icon" aria-hidden="true">{iconSrc ? <img src={iconSrc} alt="" /> : icon}</span>
      <h2>{title}</h2>
      <p>{description}</p>
      {children}
      {actionLabel && <Button variant="outline" size="sm" onClick={onAction} loading={loading} disabled={actionDisabled}>{actionLabel}</Button>}
      {showStatus && <span className={`ceopro-data-source-card__status is-${status}`}>{t(`dataConnections.statuses.${status}`)}</span>}
      {error && <small className="ceopro-data-source-card__error" role="status">{error}</small>}
    </article>
  );
}
