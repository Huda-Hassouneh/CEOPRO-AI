-- Undoes migrations/20261026000000_add_comment_action_status.sql. LOSES the owners' "noted" / "acted on" marks
-- (they are not derivable from anything else); the comments themselves stay.
ALTER TABLE reviews DROP CONSTRAINT IF EXISTS reviews_action_status_check;
ALTER TABLE reviews DROP COLUMN IF EXISTS action_at;
ALTER TABLE reviews DROP COLUMN IF EXISTS action_by;
ALTER TABLE reviews DROP COLUMN IF EXISTS action_status;
