-- Real deletion for sources whose terms require stored data to be removed or refreshed.
--
-- enforce_market_retention() only blanks reviewer names after a source's retention period; it never
-- deletes review text. YouTube's API terms require data stored from the API to be refreshed or deleted
-- within 30 days, so comments from the 'youtube_comments' source (retention_days = 30) are deleted
-- outright once they are older than the source's retention_days, measured from when they were stored.
-- Replies go with their comment (the parent link is ON DELETE SET NULL, so nothing blocks the delete);
-- sentiment results cascade. A later collection run simply stores the comments again.

CREATE OR REPLACE FUNCTION enforce_comment_retention()
RETURNS INT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    deleted INT;
BEGIN
    DELETE FROM reviews review
    USING data_sources source
    WHERE source.tenant_id = review.tenant_id AND source.source_id = review.source_id
      AND source.collector_key = 'youtube_comments'
      AND review.created_at < NOW() - (source.retention_days * INTERVAL '1 day');
    GET DIAGNOSTICS deleted = ROW_COUNT;
    RETURN deleted;
END;
$$;

REVOKE ALL ON FUNCTION enforce_comment_retention() FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        GRANT EXECUTE ON FUNCTION enforce_comment_retention() TO ceopro_app;
    END IF;
END $$;
