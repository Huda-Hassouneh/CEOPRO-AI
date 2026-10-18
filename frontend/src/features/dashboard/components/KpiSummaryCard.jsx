import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function KpiSummaryCard({ title }) {
  const { t } = useI18n();
  title ??= t("interfaceCopy.kpi");
  return <div className="kpi-summary-card">{title}</div>;
}
