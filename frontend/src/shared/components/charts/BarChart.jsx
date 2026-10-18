import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export default function BarChart() {
  const { t: copyT } = useI18n();
  return <div className='chart'>{copyT("interfaceCopy.barchart")}</div>;
}
