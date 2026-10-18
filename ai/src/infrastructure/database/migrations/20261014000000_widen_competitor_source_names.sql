-- competitor_sources.source only accepted the first source names, so a
-- discovery run with Brave or Tavily web search configured (stored as
-- brave_search / tavily_search) failed when saving its results. Also admits
-- the keyless sources added with it: place search (nominatim, photon), the
-- open company database (wikidata) and news (gdelt). Additive only.
ALTER TABLE competitor_sources DROP CONSTRAINT IF EXISTS competitor_sources_source_check;
ALTER TABLE competitor_sources ADD CONSTRAINT competitor_sources_source_check CHECK (source IN (
    'openstreetmap', 'google_places', 'google_search', 'brave_search', 'tavily_search', 'searxng',
    'apify_google_maps', 'nominatim', 'photon', 'wikidata', 'gdelt', 'manual', 'website', 'demo'));
