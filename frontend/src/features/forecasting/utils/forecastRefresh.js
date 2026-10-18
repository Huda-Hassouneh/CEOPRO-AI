import { getApiError } from "../../../shared/lib/apiErrorCore.js";

// Retain only this query's cached data on a known transient acquisition error.
// Permission/not-found errors must still hide the page and its cached data.
export function isForecastRefreshBusy(query) {
  const error = getApiError(query.error);
  return Boolean(query.isError && query.data != null &&
    error.status === 503 && error.code === "SERVICE_UNAVAILABLE" &&
    error.details?.reason === "FORECAST_DATABASE_BUSY");
}
