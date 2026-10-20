-- What the owner did about a collected comment: "noted" (seen, kept in mind) or "acted_on" (turned into a
-- price, campaign or service change). NULL = not handled yet. Additive and nullable.
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS action_status VARCHAR(12);
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS action_by UUID;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS action_at TIMESTAMPTZ;
ALTER TABLE reviews DROP CONSTRAINT IF EXISTS reviews_action_status_check;
ALTER TABLE reviews ADD CONSTRAINT reviews_action_status_check CHECK (action_status IS NULL OR action_status IN ('noted', 'acted_on'));
