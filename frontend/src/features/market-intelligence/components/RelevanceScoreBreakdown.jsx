import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function RelevanceScoreBreakdown() {
  const { t: copyT } = useI18n();
  return <div className="relevance-score-breakdown">{copyT("interfaceCopy.relevanceBreakdown")}</div>;
}
