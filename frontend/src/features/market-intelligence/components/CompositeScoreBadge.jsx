import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function CompositeScoreBadge() {
  const { t: copyT } = useI18n();
  return <span className="composite-score-badge">{copyT("interfaceCopy.compositeScore")}</span>;
}
