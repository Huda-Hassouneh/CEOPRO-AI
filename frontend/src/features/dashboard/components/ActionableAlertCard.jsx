import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function ActionableAlertCard() {
  const { t: copyT } = useI18n();
  return <div className="actionable-alert-card">{copyT("interfaceCopy.analyzeImpact")}</div>;
}
