const DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;

function dateKeyAt(epochMs, formatter) {
  const parts = Object.fromEntries(formatter.formatToParts(new Date(epochMs))
    .filter(({ type }) => type !== 'literal')
    .map(({ type, value }) => [type, value]));
  return `${parts.year}-${parts.month}-${parts.day}`;
}

function assertCalendarDate(value) {
  const match = DATE_PATTERN.exec(value || '');
  if (!match) throw new RangeError('Expected a YYYY-MM-DD calendar date.');
  const [, year, month, day] = match.map(Number);
  const check = new Date(Date.UTC(year, month - 1, day));
  if (check.getUTCFullYear() !== year || check.getUTCMonth() !== month - 1 || check.getUTCDate() !== day) {
    throw new RangeError('Invalid calendar date.');
  }
  return { year, month, day };
}

function nextCalendarDate(value) {
  const { year, month, day } = assertCalendarDate(value);
  const next = new Date(Date.UTC(year, month - 1, day + 1));
  return `${next.getUTCFullYear()}-${String(next.getUTCMonth() + 1).padStart(2, '0')}-${String(next.getUTCDate()).padStart(2, '0')}`;
}

// Find the first instant whose tenant-local calendar date is `value`. This
// handles offset changes and midnight DST transitions without assuming a
// fixed UTC offset or a 24-hour local day.
function localDayStart(value, timeZone) {
  assertCalendarDate(value);
  const formatter = new Intl.DateTimeFormat('en-US-u-ca-iso8601-nu-latn', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  });
  const target = Date.parse(`${value}T00:00:00Z`);
  let low = target - 48 * 60 * 60 * 1000;
  let high = target + 48 * 60 * 60 * 1000;
  if (dateKeyAt(low, formatter) >= value || dateKeyAt(high, formatter) < value) {
    throw new RangeError('Could not resolve the tenant-local calendar date.');
  }
  while (high - low > 1) {
    const middle = low + Math.floor((high - low) / 2);
    if (dateKeyAt(middle, formatter) >= value) high = middle;
    else low = middle;
  }
  if (dateKeyAt(high, formatter) !== value) {
    throw new RangeError('The tenant-local calendar date does not exist.');
  }
  return new Date(high).toISOString();
}

export function createReportDateRange(startDate, endDate, timeZone) {
  if (!startDate && !endDate) return { startDate: undefined, endDate: undefined };
  if (startDate) assertCalendarDate(startDate);
  if (endDate) assertCalendarDate(endDate);
  if (startDate && endDate && startDate > endDate) {
    throw new RangeError('The report start date must be on or before the end date.');
  }
  return {
    startDate: startDate ? localDayStart(startDate, timeZone) : undefined,
    endDate: endDate ? localDayStart(nextCalendarDate(endDate), timeZone) : undefined,
  };
}
