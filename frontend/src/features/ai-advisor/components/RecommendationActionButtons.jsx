import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function RecommendationActionButtons() {
  const { t: copyT } = useI18n();
  return <div className="recommendation-action-buttons">{copyT("interfaceCopy.analyzeImpactGenerateResponse")}</div>;
}
