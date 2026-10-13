import { useI18n } from '../providers/I18nProvider.jsx';

export function RoutePending() {
  const { t } = useI18n();

  return (
    <div className="ceopro-route-status" role="status" aria-live="polite">
      {t('common.loading')}
    </div>
  );
}
