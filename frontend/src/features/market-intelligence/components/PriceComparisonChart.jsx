import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function PriceComparisonChart() {
  const { t: copyT } = useI18n();
  return <div className="price-comparison-chart">{copyT("interfaceCopy.priceComparison")}</div>;
}
