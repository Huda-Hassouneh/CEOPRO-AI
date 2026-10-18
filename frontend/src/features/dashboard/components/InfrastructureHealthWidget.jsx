import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function InfrastructureHealthWidget() {
  const { t: copyT } = useI18n();
  return <div className="infrastructure-health-widget">{copyT("interfaceCopy.health")}</div>;
}
