/** Source kinds that occupy a connected-data-source slot while active. */
export const COUNTED_CONNECTED_SOURCE_TYPES = Object.freeze([
  "shopify",
  "postgresql",
  "mysql",
  "sqlserver",
  "ga4",
  "website",
  // The AI connector stores database/API sources under this shared type.
  "OWN_SYSTEM_CONNECTOR"
] as const);

/** Public Node registration choices; AI owns registration of its connector type. */
export const PERSISTENT_DATA_SOURCE_TYPES = Object.freeze([
  "shopify",
  "postgresql",
  "mysql",
  "sqlserver",
  "ga4",
  "website"
] as const);

export type PersistentDataSourceType =
  (typeof PERSISTENT_DATA_SOURCE_TYPES)[number];

export function isCountedConnectedSourceType(
  sourceType: string
): sourceType is (typeof COUNTED_CONNECTED_SOURCE_TYPES)[number] {
  return (COUNTED_CONNECTED_SOURCE_TYPES as readonly string[]).includes(
    sourceType
  );
}
