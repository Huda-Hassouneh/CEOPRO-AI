import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function TrendSparkline() {
  const { t: copyT } = useI18n();
  return <div className="trend-sparkline">{copyT("interfaceCopy.trend")}</div>;
}
