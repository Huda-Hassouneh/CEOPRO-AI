import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export default function ErrorBoundary() {
  const { t: copyT } = useI18n();
  return <div className='error-boundary'>{copyT("interfaceCopy.error")}</div>;
}
