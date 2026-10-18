import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function MultilingualFieldEditor() {
  const { t: copyT } = useI18n();
  return <div className="multilingual-field-editor">{copyT("interfaceCopy.multilingual")}</div>;
}
