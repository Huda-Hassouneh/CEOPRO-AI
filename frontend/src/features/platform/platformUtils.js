const normalize = (value) => String(value ?? '').trim().toLocaleLowerCase();

// The current platform SQL contract pages results but has no server-side
// search parameter. Keep the UI honest: this helper filters only the loaded
// page and does not imply a global search.
export function filterPlatformPage(items, query) {
  const needle = normalize(query);
  if (!needle) return items;
  return items.filter((item) => [item.business_name, item.full_name, item.email, item.country_code, item.primary_currency]
    .some((value) => normalize(value).includes(needle)));
}
