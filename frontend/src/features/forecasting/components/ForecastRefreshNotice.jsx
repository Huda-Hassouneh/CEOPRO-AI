import Button from "../../../shared/components/ui/Button.jsx";
import { isForecastRefreshBusy } from "../utils/forecastRefresh.js";

export function ForecastRefreshNotice({ query, t }) {
  if (!isForecastRefreshBusy(query)) return null;
  return <div className="forecast-refresh-notice" role="alert">
    <p>{t("demandApproved.error.refreshBusy")}</p>
    <Button size="sm" variant="outline" onClick={() => query.refetch()} disabled={query.isFetching}>
      {t("demandApproved.actions.retry")}
    </Button>
  </div>;
}
