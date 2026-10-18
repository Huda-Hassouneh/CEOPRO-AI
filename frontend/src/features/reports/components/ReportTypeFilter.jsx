import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export default function ReportTypeFilter() {
  const { t: copyT } = useI18n();
  return <div className='filter'>{copyT("interfaceCopy.reportTypeFilter")}</div>;
}
