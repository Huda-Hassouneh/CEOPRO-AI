import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function PredictedVsActualChart() {
  const { t: copyT } = useI18n();
  return <div className="predicted-vs-actual-chart">{copyT("interfaceCopy.predictionVsActual")}</div>;
}
