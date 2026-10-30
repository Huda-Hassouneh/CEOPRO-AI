export const ORANGE_COUNTRY_GROUPS = Object.freeze([
  {
    id: 'europe',
    countries: [
      ['BE', 'belgium'], ['FR', 'france'], ['LU', 'luxembourg'], ['MD', 'moldova'],
      ['PL', 'poland'], ['RO', 'romania'], ['SK', 'slovakia'], ['ES', 'spain'],
    ],
  },
  {
    id: 'africaMiddleEast',
    countries: [
      ['BW', 'botswana'], ['BF', 'burkinaFaso'], ['CM', 'cameroon'], ['CF', 'centralAfricanRepublic'],
      ['CI', 'coteDIvoire'], ['CD', 'democraticRepublicCongo'], ['EG', 'egypt'], ['GN', 'guinea'],
      ['GW', 'guineaBissau'], ['JO', 'jordan'], ['LR', 'liberia'], ['ML', 'mali'],
      ['MA', 'morocco'], ['SN', 'senegal'], ['SL', 'sierraLeone'], ['TN', 'tunisia'],
    ],
  },
].map((group) => Object.freeze({
  ...group,
  countries: Object.freeze(group.countries.map(([value, label]) => Object.freeze({
    value,
    labelKey: `onboarding.region.countries.${label}`,
  }))),
})));

export const ORANGE_COUNTRIES = Object.freeze(ORANGE_COUNTRY_GROUPS.flatMap((group) => group.countries));

const city = (value, label) => Object.freeze({
  value,
  labelKey: `onboarding.region.cities.${label}`,
});

export const ORANGE_COUNTRY_CITIES = Object.freeze({
  BE: Object.freeze([city('brussels', 'brussels'), city('antwerp', 'antwerp'), city('liege', 'liege')]),
  FR: Object.freeze([city('paris', 'paris'), city('lyon', 'lyon'), city('marseille', 'marseille')]),
  LU: Object.freeze([city('luxembourg-city', 'luxembourgCity'), city('esch-sur-alzette', 'eschSurAlzette')]),
  MD: Object.freeze([city('chisinau', 'chisinau'), city('balti', 'balti')]),
  PL: Object.freeze([city('warsaw', 'warsaw'), city('krakow', 'krakow'), city('wroclaw', 'wroclaw')]),
  RO: Object.freeze([city('bucharest', 'bucharest'), city('cluj-napoca', 'clujNapoca'), city('iasi', 'iasi')]),
  SK: Object.freeze([city('bratislava', 'bratislava'), city('kosice', 'kosice')]),
  ES: Object.freeze([city('madrid', 'madrid'), city('barcelona', 'barcelona'), city('valencia', 'valencia')]),
  BW: Object.freeze([city('gaborone', 'gaborone'), city('francistown', 'francistown')]),
  BF: Object.freeze([city('ouagadougou', 'ouagadougou'), city('bobo-dioulasso', 'boboDioulasso')]),
  CM: Object.freeze([city('yaounde', 'yaounde'), city('douala', 'douala')]),
  CF: Object.freeze([city('bangui', 'bangui'), city('bimbo', 'bimbo')]),
  CI: Object.freeze([city('abidjan', 'abidjan'), city('yamoussoukro', 'yamoussoukro'), city('bouake', 'bouake')]),
  CD: Object.freeze([city('kinshasa', 'kinshasa'), city('lubumbashi', 'lubumbashi'), city('goma', 'goma')]),
  EG: Object.freeze([city('cairo', 'cairo'), city('alexandria', 'alexandria'), city('giza', 'giza')]),
  GN: Object.freeze([city('conakry', 'conakry'), city('nzerekore', 'nzerekore')]),
  GW: Object.freeze([city('bissau', 'bissau'), city('bafata', 'bafata')]),
  JO: Object.freeze([city('amman', 'amman'), city('irbid', 'irbid'), city('zarqa', 'zarqa'), city('aqaba', 'aqaba')]),
  LR: Object.freeze([city('monrovia', 'monrovia'), city('gbarnga', 'gbarnga')]),
  ML: Object.freeze([city('bamako', 'bamako'), city('sikasso', 'sikasso')]),
  MA: Object.freeze([city('casablanca', 'casablanca'), city('rabat', 'rabat'), city('marrakesh', 'marrakesh')]),
  SN: Object.freeze([city('dakar', 'dakar'), city('thies', 'thies'), city('saint-louis', 'saintLouis')]),
  SL: Object.freeze([city('freetown', 'freetown'), city('bo', 'bo')]),
  TN: Object.freeze([city('tunis', 'tunis'), city('sfax', 'sfax'), city('sousse', 'sousse')]),
});

export const getCitiesForCountry = (countryCode) => ORANGE_COUNTRY_CITIES[countryCode] || [];

export const isSupportedCountryCity = (countryCode, cityValue) => (
  getCitiesForCountry(countryCode).some((item) => item.value === cityValue)
);
