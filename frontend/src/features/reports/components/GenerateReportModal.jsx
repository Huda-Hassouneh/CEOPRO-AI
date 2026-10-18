import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export default function GenerateReportModal() {
  const { t: copyT } = useI18n();
  return <section className='panel'><h2>{copyT("interfaceCopy.generateReport")}</h2></section>;
}
