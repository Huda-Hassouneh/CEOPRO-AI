import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function HorizonToggle() {
  const { t: copyT } = useI18n();
  return <div className="horizon-toggle">{copyT("interfaceCopy.dailyWeeklyMonthly")}</div>;
}
