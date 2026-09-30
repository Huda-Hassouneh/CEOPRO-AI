/** Calendar dates in this API are UTC, with inclusive start/end boundaries. */
export const DAY_MS = 86_400_000;
export const dayKey = (value: Date) => value.toISOString().slice(0, 10);
export const utcDay = (value: Date) => new Date(`${dayKey(value)}T00:00:00Z`);
export const addDays = (value: Date, days: number) => new Date(value.getTime() + days * DAY_MS);

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
  if (value == null || value === "" || typeof value === "boolean") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
};

export function forecastWindow(row: ForecastRow) {
  // A stored interval represents a total for that interval, even when a target
  // date is also present. Never smear an interval total across individual days.
  if (row.forecast_start_date && row.forecast_end_date) {
    if (row.forecast_end_date < row.forecast_start_date) return null;
    return {
      start: utcDay(row.forecast_start_date),
      end: utcDay(row.forecast_end_date)
    };
  }

  // A half-populated interval has ambiguous units and must not be guessed.
  if (row.forecast_start_date || row.forecast_end_date) return null;
  if (!row.forecast_target_date) return null;

  const target = utcDay(row.forecast_target_date);
  return { start: target, end: target };
}

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
    if (!latest.has(key)) latest.set(key, row);
  }

  return [...latest.values()].sort(
    (a, b) =>
      forecastWindow(a)!.start.getTime() - forecastWindow(b)!.start.getTime() ||
      forecastWindow(a)!.end.getTime() - forecastWindow(b)!.end.getTime()
  );
}

export function interval(row: ForecastRow) {
  const lower = finiteNumber(row.confidence_range_lower);
  const upper = finiteNumber(row.confidence_range_upper);

  return lower != null &&
    upper != null &&
    lower >= 0 &&
    lower <= row.expected_demand &&
    upper >= row.expected_demand
    ? { lower, upper }
    : { lower: null, upper: null };
}

function summarizeCoverage<T extends ForecastRow>(
  rows: T[],
  start: Date,
  days: number,
  asOf: Date
) {
  const end = addDays(start, days - 1);
  const selected = latestForecasts(rows, asOf).filter((row) => {
    const window = forecastWindow(row)!;
    return window.start <= end && window.end >= start;
  });

  const contained = selected.filter((row) => {
    const window = forecastWindow(row)!;
    return window.start >= start && window.end <= end;
  });

  const covered = new Set<string>();
  let overlaps = false;

  for (const row of selected) {
    const window = forecastWindow(row)!;
    const firstCoveredDay = window.start < start ? start : window.start;

    for (
      let date = firstCoveredDay;
      date <= window.end && date <= end;
      date = addDays(date, 1)
    ) {
      const key = dayKey(date);
      if (covered.has(key)) overlaps = true;
      covered.add(key);
    }
  }

  const complete =
    !overlaps &&
    contained.length === selected.length &&
    covered.size === days;

  const expectedDemand = complete
    ? contained.reduce((sum, row) => sum + row.expected_demand, 0)
    : null;

  // A calibrated interval may be returned only when the requested horizon is
  // represented by one stored interval. Independent marginal intervals must not
  // be summed into a fabricated calibrated range.
  const confidenceRange =
    complete && contained.length === 1
      ? interval(contained[0]!)
      : { lower: null, upper: null };

  const daily = contained.filter((row) => {
    const window = forecastWindow(row)!;
    return window.start.getTime() === window.end.getTime();
  });

  return {
    selected,
    contained,
    expectedDemand,
    confidenceRange,
    complete,
    overlaps,
    daily,
    coveredDays: covered.size,
    startDate: dayKey(start),
    endDate: dayKey(end)
  };
}

function compareDemand(current: number, previous: number) {
  if (current > previous) return "increasing" as const;
  if (current < previous) return "decreasing" as const;
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
    // When the requested horizon is stored as daily forecasts, trend describes
    // the direction across the requested forecast horizon.
    if (current.daily.length === days && current.daily.length > 1) {
      const first = current.daily[0]!;
      const last = current.daily[current.daily.length - 1]!;
      trend = compareDemand(last.expected_demand, first.expected_demand);
    } else {
      // A single 7/30-day aggregate cannot reveal an intra-period daily trend.
      // Compare it with the immediately preceding complete horizon instead.
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
    selected: current.selected,
    expectedDemand: current.expectedDemand,
    confidenceRange: current.confidenceRange,
    trend,
    status,
    coveredDays: current.coveredDays,
    startDate: current.startDate,
    endDate: current.endDate
  };
}
