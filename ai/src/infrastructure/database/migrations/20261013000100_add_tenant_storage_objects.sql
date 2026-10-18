-- The size of every file a company stores in object storage outside the
-- assistant's documents (rag_documents_metadata already records those):
-- marketing images (uploaded, background-removed, AI-generated) and the
-- parsed results kept for each data upload. The plan's storage limit
-- counts both (core/usage.py). Additive only; deleting a company removes
-- its rows with it.
CREATE TABLE IF NOT EXISTS tenant_storage_objects (
    tenant_id UUID NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,
    bucket VARCHAR(100) NOT NULL,
    object_key TEXT NOT NULL,
    size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0),
    kind VARCHAR(40) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (bucket, object_key)
);
CREATE INDEX IF NOT EXISTS idx_tenant_storage_objects_tenant ON tenant_storage_objects (tenant_id);

ALTER TABLE tenant_storage_objects ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_storage_objects FORCE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'tenant_storage_objects' AND policyname = 'isolation_tenant_storage_objects') THEN
        CREATE POLICY isolation_tenant_storage_objects ON tenant_storage_objects FOR ALL USING (tenant_id = get_current_tenant());
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_storage_objects TO ceopro_app;
    END IF;
END $$;
