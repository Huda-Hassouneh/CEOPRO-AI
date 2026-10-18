-- Real gap found in first-customer acceptance testing: an uploaded file's
-- name was never stored anywhere in the database (data_sources is one row
-- per tenant per file type, named "Manual File Upload"), so the Connect
-- Data page's "Recent Data Activity" and the dashboard activity feed could
-- not say WHICH file was imported - every upload read "Manual File
-- Upload". Display metadata only; never used to build a filesystem path.
ALTER TABLE ingestion_jobs ADD COLUMN IF NOT EXISTS file_name VARCHAR(255);
