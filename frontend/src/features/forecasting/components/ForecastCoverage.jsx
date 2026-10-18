import { coveragePresentation } from "../utils/forecastPresentation.js";
export function ForecastCoverage({ coverage, periodDays, t }) {
  const state = coveragePresentation(coverage, periodDays);
  return <span className={`forecast-coverage is-${state.status}`}>
    <strong>{t(`demandApproved.coverage.${state.status}`)}</strong>
    <span>{t("demandApproved.coverage.count", { covered: state.covered, total: state.total })}</span>
  </span>;
}
