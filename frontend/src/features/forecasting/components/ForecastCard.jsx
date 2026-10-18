import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function ForecastCard() {
  const { t: copyT } = useI18n();
  return <div className="forecast-card">{copyT("interfaceCopy.forecast")}</div>;
}
