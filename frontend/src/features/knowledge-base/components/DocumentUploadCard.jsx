import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function DocumentUploadCard() {
  const { t: copyT } = useI18n();
  return <div className="document-upload-card">{copyT("interfaceCopy.uploadDocument")}</div>;
}
