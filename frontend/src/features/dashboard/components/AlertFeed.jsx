import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function AlertFeed() {
  const { t: copyT } = useI18n();
  return <div className="alert-feed">{copyT("interfaceCopy.alerts")}</div>;
}
