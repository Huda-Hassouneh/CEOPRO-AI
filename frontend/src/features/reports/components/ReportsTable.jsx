import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export default function ReportsTable() {
  const { t: copyT } = useI18n();
  return <section className='panel'><h2>{copyT("interfaceCopy.reportsTable")}</h2></section>;
}
