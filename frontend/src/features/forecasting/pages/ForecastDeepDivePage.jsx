import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { DashboardLayout } from '../../../app/layouts/DashboardLayout.jsx';

export function ForecastDeepDivePage() {
  const { t: copyT } = useI18n();
  return (
    <DashboardLayout>
      <div>{copyT("interfaceCopy.forecastDeepDive")}</div>
    </DashboardLayout>
  );
}
