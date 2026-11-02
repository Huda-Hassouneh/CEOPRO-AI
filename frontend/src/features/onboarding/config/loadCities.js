// Vite emits a separate lazy asset per country. The global city dataset is
// never included in the initial application bundle or fetched from a provider.
const catalogs = import.meta.glob('../../../shared/config/locations/[A-Z][A-Z].json', { import: 'default' });

export async function loadCities(country) {
  const load = catalogs[`../../../shared/config/locations/${country}.json`];
  if (!load) throw new Error('Unsupported country');
  return load();
}
