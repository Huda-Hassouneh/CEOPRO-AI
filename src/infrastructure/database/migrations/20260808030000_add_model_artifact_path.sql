-- Closes PENDING_ACTIONS.md #7: model_versions had no column to point a
-- trained model version at its MinIO-stored binary
-- (MINIO_STORAGE_ARCHITECTURE.md's ceopro-ai-artifacts bucket path format,
-- tenant_{tenant_id}/models/{model_type}_v{version}.bin), so only
-- metrics/version metadata could be recorded, never the artifact itself.

ALTER TABLE model_versions ADD COLUMN IF NOT EXISTS artifact_path VARCHAR(500);
