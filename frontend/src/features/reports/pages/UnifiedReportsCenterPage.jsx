import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export default function UnifiedReportsCenterPage() {
  const { t: copyT } = useI18n();
  return <section className='page'><h1>{copyT("interfaceCopy.unifiedReportsCenter")}</h1></section>;
}
