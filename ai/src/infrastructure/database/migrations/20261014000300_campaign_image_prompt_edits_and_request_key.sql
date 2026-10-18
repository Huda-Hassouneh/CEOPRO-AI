-- Marketing campaigns as one editable, saved package:
-- - image_prompt: an English description of the campaign image, written
--   with the copy, so Arabic campaigns get as good an image as English ones;
-- - request_key: the Studio's own id for one "Generate" press, so pressing
--   twice (or a retried request) returns the same campaign instead of a
--   second one;
-- - updated_at: when the owner last edited the copy.
-- Additive only.
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS image_prompt TEXT;
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS request_key VARCHAR(80);
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE;
CREATE UNIQUE INDEX IF NOT EXISTS uq_campaigns_request_key ON campaigns (tenant_id, request_key) WHERE request_key IS NOT NULL;
