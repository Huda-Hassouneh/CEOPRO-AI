import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function ExceptionBadge() {
  const { t: copyT } = useI18n();
  return <span className="exception-badge">{copyT("interfaceCopy.exception")}</span>;
}
