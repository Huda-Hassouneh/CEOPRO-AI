-- When each person last got their email summary of alerts for a company
-- (src/ai/notification_digest.py). The row is claimed before sending, so
-- several API instances never send the same summary twice.
CREATE TABLE IF NOT EXISTS notification_digests (
    tenant_id UUID NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    last_sent_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (tenant_id, user_id)
);

ALTER TABLE notification_digests ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_digests FORCE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'notification_digests' AND policyname = 'isolation_notification_digests') THEN
        CREATE POLICY isolation_notification_digests ON notification_digests FOR ALL USING (tenant_id = get_current_tenant());
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON notification_digests TO ceopro_app;
    END IF;
END $$;
