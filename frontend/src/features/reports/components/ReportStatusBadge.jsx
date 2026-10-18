import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export default function ReportStatusBadge() {
  const { t: copyT } = useI18n();
  return <span className='badge'>{copyT("interfaceCopy.ready")}</span>;
}
