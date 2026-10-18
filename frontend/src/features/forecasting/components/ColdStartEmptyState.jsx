import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function ColdStartEmptyState() {
  const { t: copyT } = useI18n();
  return <div className="cold-start-empty-state">{copyT("interfaceCopy.coldStartEmptyState")}</div>;
}
