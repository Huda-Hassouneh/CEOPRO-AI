// Every country a business can operate in, with the currency it usually
// trades in. Names come from the browser (Intl.DisplayNames) in the
// interface language, so the list is complete in English and Arabic
// without a translation table.
const COUNTRY_CURRENCY = {
  AD: 'EUR', AE: 'AED', AF: 'AFN', AG: 'XCD', AL: 'ALL', AM: 'AMD', AO: 'AOA', AR: 'ARS', AT: 'EUR', AU: 'AUD',
  AZ: 'AZN', BA: 'BAM', BB: 'BBD', BD: 'BDT', BE: 'EUR', BF: 'XOF', BG: 'BGN', BH: 'BHD', BI: 'BIF', BJ: 'XOF',
  BN: 'BND', BO: 'BOB', BR: 'BRL', BS: 'BSD', BT: 'BTN', BW: 'BWP', BY: 'BYN', BZ: 'BZD', CA: 'CAD', CD: 'CDF',
  CF: 'XAF', CG: 'XAF', CH: 'CHF', CI: 'XOF', CL: 'CLP', CM: 'XAF', CN: 'CNY', CO: 'COP', CR: 'CRC', CV: 'CVE',
  CY: 'EUR', CZ: 'CZK', DE: 'EUR', DJ: 'DJF', DK: 'DKK', DM: 'XCD', DO: 'DOP', DZ: 'DZD', EC: 'USD', EE: 'EUR',
  EG: 'EGP', ER: 'ERN', ES: 'EUR', ET: 'ETB', FI: 'EUR', FJ: 'FJD', FR: 'EUR', GA: 'XAF', GB: 'GBP', GD: 'XCD',
  GE: 'GEL', GH: 'GHS', GM: 'GMD', GN: 'GNF', GQ: 'XAF', GR: 'EUR', GT: 'GTQ', GW: 'XOF', GY: 'GYD', HK: 'HKD',
  HN: 'HNL', HR: 'EUR', HT: 'HTG', HU: 'HUF', ID: 'IDR', IE: 'EUR', IN: 'INR', IQ: 'IQD', IS: 'ISK', IT: 'EUR',
  JM: 'JMD', JO: 'JOD', JP: 'JPY', KE: 'KES', KG: 'KGS', KH: 'KHR', KM: 'KMF', KN: 'XCD', KR: 'KRW', KW: 'KWD',
  KZ: 'KZT', LA: 'LAK', LB: 'LBP', LC: 'XCD', LI: 'CHF', LK: 'LKR', LR: 'LRD', LS: 'LSL', LT: 'EUR', LU: 'EUR',
  LV: 'EUR', LY: 'LYD', MA: 'MAD', MC: 'EUR', MD: 'MDL', ME: 'EUR', MG: 'MGA', MK: 'MKD', ML: 'XOF', MM: 'MMK',
  MN: 'MNT', MO: 'MOP', MR: 'MRU', MT: 'EUR', MU: 'MUR', MV: 'MVR', MW: 'MWK', MX: 'MXN', MY: 'MYR', MZ: 'MZN',
  NA: 'NAD', NE: 'XOF', NG: 'NGN', NI: 'NIO', NL: 'EUR', NO: 'NOK', NP: 'NPR', NZ: 'NZD', OM: 'OMR', PA: 'PAB',
  PE: 'PEN', PG: 'PGK', PH: 'PHP', PK: 'PKR', PL: 'PLN', PS: 'ILS', PT: 'EUR', PY: 'PYG', QA: 'QAR', RO: 'RON',
  RS: 'RSD', RW: 'RWF', SA: 'SAR', SB: 'SBD', SC: 'SCR', SD: 'SDG', SE: 'SEK', SG: 'SGD', SI: 'EUR', SK: 'EUR',
  SL: 'SLE', SM: 'EUR', SN: 'XOF', SO: 'SOS', SR: 'SRD', SS: 'SSP', ST: 'STN', SV: 'USD', SY: 'SYP', SZ: 'SZL',
  TD: 'XAF', TG: 'XOF', TH: 'THB', TJ: 'TJS', TL: 'USD', TM: 'TMT', TN: 'TND', TO: 'TOP', TR: 'TRY', TT: 'TTD',
  TW: 'TWD', TZ: 'TZS', UA: 'UAH', UG: 'UGX', US: 'USD', UY: 'UYU', UZ: 'UZS', VC: 'XCD', VE: 'VES', VN: 'VND',
  VU: 'VUV', WS: 'WST', YE: 'YER', ZA: 'ZAR', ZM: 'ZMW', ZW: 'ZWL',
};

export const COUNTRY_CODES = Object.freeze(Object.keys(COUNTRY_CURRENCY));

export function defaultCurrencyFor(countryCode) {
  return COUNTRY_CURRENCY[(countryCode || '').toUpperCase()] || 'USD';
}

function displayNames(locale, type) {
  try {
    return new Intl.DisplayNames([locale || 'en'], { type });
  } catch {
    return null;
  }
}

// [{ value: 'JO', label: 'Jordan' }, ...] sorted by name in the interface language.
export function countryOptions(locale) {
  const names = displayNames(locale, 'region');
  const collator = new Intl.Collator(locale || 'en');
  return COUNTRY_CODES
    .map((value) => ({ value, label: names?.of(value) || value }))
    .sort((a, b) => collator.compare(a.label, b.label));
}

export function currencyOptions(locale) {
  const names = displayNames(locale, 'currency');
  const codes = [...new Set(Object.values(COUNTRY_CURRENCY))].sort();
  return codes.map((value) => ({ value, label: `${value} · ${names?.of(value) || value}` }));
}

export function countryName(code, locale) {
  return displayNames(locale, 'region')?.of(code) || code;
}
