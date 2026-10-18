import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export default function LoadingSpinner() {
  const { t: copyT } = useI18n();
  return <div className='spinner'>{copyT("common.loading")}</div>;
}
