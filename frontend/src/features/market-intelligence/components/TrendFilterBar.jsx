import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function TrendFilterBar() {
  const { t: copyT } = useI18n();
  return <div className="trend-filter-bar">{copyT("interfaceCopy.trendFilters")}</div>;
}
