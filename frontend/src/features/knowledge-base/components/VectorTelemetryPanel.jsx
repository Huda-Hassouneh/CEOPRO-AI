import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function VectorTelemetryPanel() {
  const { t: copyT } = useI18n();
  return <div className="vector-telemetry-panel">{copyT("interfaceCopy.vectorTelemetry")}</div>;
}
