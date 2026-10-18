import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export default function ConfirmDialog() {
  const { t: copyT } = useI18n();
  return <div className='dialog'>{copyT("common.confirm")}</div>;
}
