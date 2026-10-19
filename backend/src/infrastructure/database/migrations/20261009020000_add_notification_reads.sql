-- When each person last opened their alerts, per company: alerts newer
-- than this are unread. Alerts themselves are derived from live data.
CREATE TABLE IF NOT EXISTS notification_reads (
    tenant_id UUID NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    last_read_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, user_id)
);
ALTER TABLE notification_reads ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_reads FORCE ROW LEVEL SECURITY;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'notification_reads' AND policyname = 'isolation_notification_reads') THEN
        CREATE POLICY isolation_notification_reads ON notification_reads FOR ALL USING (tenant_id = get_current_tenant());
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON notification_reads TO ceopro_app;
    END IF;
END $$;
