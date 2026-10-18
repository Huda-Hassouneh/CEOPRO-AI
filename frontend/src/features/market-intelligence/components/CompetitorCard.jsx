import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function CompetitorCard() {
  const { t: copyT } = useI18n();
  return <div className="competitor-card">{copyT("interfaceCopy.competitor")}</div>;
}
