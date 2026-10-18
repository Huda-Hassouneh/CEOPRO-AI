import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export default function LineChart() {
  const { t: copyT } = useI18n();
  return <div className='chart'>{copyT("interfaceCopy.linechart")}</div>;
}
