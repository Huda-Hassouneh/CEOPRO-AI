import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function CompetitorAlertThresholdForm() {
  const { t: copyT } = useI18n();
  return <div className="competitor-alert-threshold-form">{copyT("interfaceCopy.alertThreshold")}</div>;
}
