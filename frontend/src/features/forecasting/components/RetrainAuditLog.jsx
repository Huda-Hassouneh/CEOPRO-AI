import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function RetrainAuditLog() {
  const { t: copyT } = useI18n();
  return <div className="retrain-audit-log">{copyT("interfaceCopy.retrainAuditLog")}</div>;
}
