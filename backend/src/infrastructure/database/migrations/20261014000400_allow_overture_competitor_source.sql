-- Overture Maps places (open data, read from the Overture Maps Foundation's
-- public bucket) as a competitor source.
ALTER TABLE competitor_sources DROP CONSTRAINT IF EXISTS competitor_sources_source_check;
ALTER TABLE competitor_sources ADD CONSTRAINT competitor_sources_source_check CHECK (source IN (
    'openstreetmap', 'overture', 'google_places', 'google_search', 'brave_search', 'tavily_search', 'searxng',
    'apify_google_maps', 'nominatim', 'photon', 'wikidata', 'gdelt', 'manual', 'website', 'demo'));
