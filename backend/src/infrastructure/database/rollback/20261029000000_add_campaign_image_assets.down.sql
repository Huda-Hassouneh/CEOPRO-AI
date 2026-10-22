-- Undoes migrations/20261029000000_add_campaign_image_assets.sql. The gallery records are lost; each campaign keeps
-- its attached image (campaigns.generated_image_key). Stored files of other gallery images stay in object storage
-- (and in tenant_storage_objects) until the campaign is deleted, which removes every file under its prefix.
DROP TABLE IF EXISTS campaign_image_assets;
DELETE FROM provider_cost_schedules
 WHERE budget_kind = 'ai' AND provider = 'local' AND operation = 'image_generation' AND unit = 'image';
