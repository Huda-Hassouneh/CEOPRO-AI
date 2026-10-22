-- Undoes migrations/20261030000000_add_image_generation_jobs.sql. Queued and finished job records are lost; images
-- already made stay in their campaigns' galleries.
DROP FUNCTION IF EXISTS image_generation_capacity(INTEGER, INTEGER);
DROP FUNCTION IF EXISTS claim_image_generation_job(TEXT, INTEGER);
DROP TABLE IF EXISTS image_workers;
DROP TABLE IF EXISTS image_generation_jobs;
