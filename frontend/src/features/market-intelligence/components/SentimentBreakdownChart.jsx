import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function SentimentBreakdownChart() {
  const { t: copyT } = useI18n();
  return <div className="sentiment-breakdown-chart">{copyT("interfaceCopy.sentimentBreakdown")}</div>;
}
