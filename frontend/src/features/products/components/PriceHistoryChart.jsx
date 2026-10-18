import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function PriceHistoryChart() {
  const { t: copyT } = useI18n();
  return <div className="price-history-chart">{copyT("interfaceCopy.priceHistory")}</div>;
}
