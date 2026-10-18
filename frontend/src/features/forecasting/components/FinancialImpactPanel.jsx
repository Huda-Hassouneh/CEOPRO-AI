import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function FinancialImpactPanel() {
  const { t: copyT } = useI18n();
  return <div className="financial-impact-panel">{copyT("interfaceCopy.financialImpact")}</div>;
}
