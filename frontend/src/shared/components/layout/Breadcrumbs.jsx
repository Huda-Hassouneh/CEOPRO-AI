import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export default function Breadcrumbs() {
  const { t: copyT } = useI18n();
  return <nav className='breadcrumbs'>{copyT("interfaceCopy.breadcrumbs")}</nav>;
}
