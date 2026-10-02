/** Calendar dates in this API are UTC, with inclusive start/end boundaries. */
export const DAY_MS = 86_400_000;

export const dayKey = (value: Date) => value.toISOString().slice(0, 10);

export const utcDay = (value: Date) => new Date(`${dayKey(value)}T00:00:00Z`);

export const addDays = (value: Date, days: number) =>
  new Date(value.getTime() + days * DAY_MS);

export type ForecastRow = {
  forecast_id: string;
  forecast_start_date: Date | null;
  forecast_end_date: Date | null;
  forecast_target_date: Date | null;
  expected_demand: number;
  confidence_range_lower: unknown;
  confidence_range_upper: unknown;
  created_at: Date | null;
  model_version: string;
};

export const finiteNumber = (value: unknown): number | null => {
  if (value == null || value === "" || typeof value === "boolean") {
    return null;
  }

  const number = Number(value);
  return Number.isFinite(number) ? number : null;
};

/**
 * Returns the inclusive UTC forecast window represented by a stored forecast.
 *
 * Multi-day rows represent aggregate forecasts for the complete interval.
 * Daily rows have start === end.
 */
export function forecastWindow(row: ForecastRow) {
  if (row.forecast_start_date && row.forecast_end_date) {
    const start = utcDay(row.forecast_start_date);
    const end = utcDay(row.forecast_end_date);

    if (end < start) return null;

    return { start, end };
  }

  // A half-populated interval is ambiguous and must not be guessed.
  if (row.forecast_start_date || row.forecast_end_date) {
    return null;
  }

  if (!row.forecast_target_date) {
    return null;
  }

  const target = utcDay(row.forecast_target_date);

  return {
    start: target,
    end: target
  };
}

/**
 * Returns the number of calendar days represented by a forecast.
 *
 * Examples:
 * Oct 1 -> Oct 1  = 1 day
 * Oct 1 -> Oct 7  = 7 days
 * Oct 1 -> Oct 30 = 30 days
 */
export function forecastWindowDays(row: ForecastRow): number | null {
  const window = forecastWindow(row);

  if (!window) {
    return null;
  }

  return (
    Math.round((window.end.getTime() - window.start.getTime()) / DAY_MS) + 1
  );
}

/**
 * Keep only the latest stored version of each unique forecast window.
 */
export function latestForecasts<T extends ForecastRow>(rows: T[], asOf: Date) {
  const latest = new Map<string, T>();

  for (const row of [...rows].sort(
    (a, b) =>
      (b.created_at?.getTime() ?? -Infinity) -
        (a.created_at?.getTime() ?? -Infinity) ||
      b.forecast_id.localeCompare(a.forecast_id)
  )) {
    const window = forecastWindow(row);

    if (
      !window ||
      (row.created_at && row.created_at > asOf) ||
      !Number.isFinite(row.expected_demand) ||
      row.expected_demand < 0
    ) {
      continue;
    }

    const key = `${dayKey(window.start)}:${dayKey(window.end)}`;

    if (!latest.has(key)) {
      latest.set(key, row);
    }
  }

  return [...latest.values()].sort(
    (a, b) =>
      forecastWindow(a)!.start.getTime() - forecastWindow(b)!.start.getTime() ||
      forecastWindow(a)!.end.getTime() - forecastWindow(b)!.end.getTime()
  );
}

/**
 * Validate and normalize a forecast's stored confidence interval.
 *
 * A valid interval must surround the expected demand:
 *
 * lower <= expected_demand <= upper
 */
export function interval(row: ForecastRow) {
  const lower = finiteNumber(row.confidence_range_lower);
  const upper = finiteNumber(row.confidence_range_upper);

  if (
    lower == null ||
    upper == null ||
    lower < 0 ||
    lower > row.expected_demand ||
    upper < row.expected_demand
  ) {
    return {
      lower: null,
      upper: null
    };
  }

  return {
    lower,
    upper
  };
}

function sameDay(left: Date, right: Date) {
  return left.getTime() === right.getTime();
}

/**
 * Analyze how a collection of non-ambiguous forecast rows covers the
 * requested horizon.
 */
function analyzeCoverage<T extends ForecastRow>(
  rows: T[],
  start: Date,
  end: Date
) {
  const covered = new Set<string>();
  let overlaps = false;

  for (const row of rows) {
    const window = forecastWindow(row);

    if (!window) {
      continue;
    }

    for (let date = window.start; date <= window.end; date = addDays(date, 1)) {
      if (date < start || date > end) {
        continue;
      }

      const key = dayKey(date);

      if (covered.has(key)) {
        overlaps = true;
      }

      covered.add(key);
    }
  }

  const requestedDays =
    Math.round((end.getTime() - start.getTime()) / DAY_MS) + 1;

  return {
    coveredDays: covered.size,
    overlaps,
    complete: rows.length > 0 && !overlaps && covered.size === requestedDays
  };
}

function summarizeCoverage<T extends ForecastRow>(
  rows: T[],
  start: Date,
  days: number,
  asOf: Date
) {
  const end = addDays(start, days - 1);

  const latest = latestForecasts(rows, asOf);

  /**
   * All forecasts touching the requested period.
   *
   * This intentionally may include multiple granularities:
   * daily, 7-day, 30-day, etc.
   */
  const selected = latest.filter((row) => {
    const window = forecastWindow(row)!;

    return window.start <= end && window.end >= start;
  });

  /**
   * Forecasts completely contained inside the requested period.
   */
  const contained = selected.filter((row) => {
    const window = forecastWindow(row)!;

    return window.start >= start && window.end <= end;
  });

  /**
   * Daily forecasts remain available independently for chart/trend usage.
   */
  const daily = contained.filter((row) => forecastWindowDays(row) === 1);

  /**
   * Preferred summary source:
   *
   * For a 7-day request:
   *   use the exact 7-day forecast if one exists.
   *
   * For a 30-day request:
   *   use the exact 30-day forecast if one exists.
   *
   * Daily forecasts or other horizon rows must not make this forecast appear
   * "overlapping".
   */
  const exactHorizon = contained.find((row) => {
    const window = forecastWindow(row)!;

    return (
      sameDay(window.start, start) &&
      sameDay(window.end, end) &&
      forecastWindowDays(row) === days
    );
  });

  let summaryRows: T[] = [];

  if (exactHorizon) {
    /**
     * Best case:
     *
     * The forecasting model explicitly produced the requested horizon.
     * Its expected demand and confidence interval may therefore be used
     * directly.
     */
    summaryRows = [exactHorizon];
  } else {
    /**
     * Fallback #1:
     *
     * If every requested day has a daily forecast, the expected demand can
     * safely be summed because expected values are additive.
     *
     * Confidence intervals are NOT summed.
     */
    const dailyCoverage = analyzeCoverage(daily, start, end);

    if (dailyCoverage.complete && daily.length === days) {
      summaryRows = daily;
    } else {
      /**
       * Fallback #2:
       *
       * Preserve support for non-daily interval forecasts that tile the
       * requested horizon without overlapping.
       *
       * Example:
       *   Oct 1 -> Oct 7
       *   Oct 8 -> Oct 14
       *   ...
       *
       * These may contribute to expected demand, but multiple confidence
       * intervals are still not combined.
       */
      const intervalRows = contained.filter(
        (row) => (forecastWindowDays(row) ?? 0) > 1
      );

      const intervalCoverage = analyzeCoverage(intervalRows, start, end);

      if (intervalCoverage.complete) {
        summaryRows = intervalRows;
      } else {
        /**
         * Keep the best available contained rows for status diagnostics.
         *
         * They will remain partial/overlapping rather than fabricating a
         * complete result.
         */
        summaryRows = intervalRows.length > 0 ? intervalRows : daily;
      }
    }
  }

  const coverage = analyzeCoverage(summaryRows, start, end);

  const complete = coverage.complete;

  const expectedDemand = complete
    ? summaryRows.reduce((sum, row) => sum + row.expected_demand, 0)
    : null;

  /**
   * Only expose a stored/calibrated confidence range when ONE forecast row
   * represents the requested summary horizon.
   *
   * Never sum lower/upper bounds from independent forecasts.
   */
  const confidenceRange =
    complete && summaryRows.length === 1
      ? interval(summaryRows[0]!)
      : {
          lower: null,
          upper: null
        };

  return {
    selected,
    contained,
    summaryRows,
    expectedDemand,
    confidenceRange,
    complete,
    overlaps: coverage.overlaps,
    daily,
    coveredDays: coverage.coveredDays,
    startDate: dayKey(start),
    endDate: dayKey(end)
  };
}

function compareDemand(current: number, previous: number) {
  if (current > previous) {
    return "increasing" as const;
  }

  if (current < previous) {
    return "decreasing" as const;
  }

  return "stable" as const;
}

export function summarizeForecasts<T extends ForecastRow>(
  rows: T[],
  start: Date,
  days: number,
  asOf: Date
) {
  const current = summarizeCoverage(rows, start, days, asOf);

  let trend: "increasing" | "decreasing" | "stable" | null = null;

  if (current.complete && current.expectedDemand != null) {
    /**
     * Prefer daily movement when a complete daily forecast series exists.
     *
     * This remains independent of whether an exact 7/30-day summary forecast
     * also exists.
     */
    if (current.daily.length === days && current.daily.length > 1) {
      const first = current.daily[0]!;
      const last = current.daily[current.daily.length - 1]!;

      trend = compareDemand(last.expected_demand, first.expected_demand);
    } else {
      /**
       * An aggregate 7/30-day forecast alone cannot describe intra-horizon
       * daily direction.
       *
       * Compare it with the immediately preceding equivalent horizon instead.
       */
      const previousStart = addDays(start, -days);

      const previous = summarizeCoverage(rows, previousStart, days, asOf);

      if (previous.complete && previous.expectedDemand != null) {
        trend = compareDemand(current.expectedDemand, previous.expectedDemand);
      }
    }
  }

  const status = !current.selected.length
    ? "unavailable"
    : current.overlaps
      ? "overlapping"
      : current.complete
        ? "complete"
        : "partial";

  return {
    /**
     * Keep all intersecting latest forecasts available to callers.
     *
     * This is important because the service still needs daily rows for
     * charting even when summary metrics use a 7/30-day aggregate row.
     */
    selected: current.selected,

    /**
     * Rows actually used to calculate the summary.
     *
     * The service can use this on the next step when it needs to know which
     * forecast produced the summary/recommendation.
     */
    summaryRows: current.summaryRows,

    expectedDemand: current.expectedDemand,
    confidenceRange: current.confidenceRange,
    trend,
    status,
    coveredDays: current.coveredDays,
    startDate: current.startDate,
    endDate: current.endDate
  };
}
