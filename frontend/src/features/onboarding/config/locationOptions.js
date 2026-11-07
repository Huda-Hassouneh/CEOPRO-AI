import { LEGACY_COUNTRY_CITIES } from './countries.js';

// Keep the existing slug/string storage contract. No coordinates, state or
// timezone is inferred from a city choice.
export function cityValue(name) {
  return name.normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, '-').replace(/^-|-$/g, '');
}

export function cityOptions(country, names, locale, t, savedRegion = {}) {
  const options = new Map();
  for (const item of LEGACY_COUNTRY_CITIES[country] || []) {
    options.set(item.value, { value: item.value, label: t(item.labelKey) });
  }
  for (const name of names) {
    const value = cityValue(name);
    if (value && value.length <= 100 && !options.has(value)) options.set(value, { value, label: name });
  }
  // Previously saved strings (including historical spelling) remain readable;
  // this exception never carries a city to a different country.
  if (savedRegion.country === country && savedRegion.city && !options.has(savedRegion.city)) {
    options.set(savedRegion.city, { value: savedRegion.city, label: savedRegion.city });
  }
  const collator = new Intl.Collator(locale);
  return [...options.values()].sort((a, b) => collator.compare(a.label, b.label));
}

export function filterCityOptions(options, search, selected) {
  const needle = cityValue(search);
  const matches = options.filter((item) => !needle || cityValue(item.label).includes(needle) || item.value.includes(needle));
  const visible = matches.slice(0, 200);
  const current = options.find((item) => item.value === selected);
  if (current && !visible.some((item) => item.value === selected)) visible.unshift(current);
  return visible;
}
