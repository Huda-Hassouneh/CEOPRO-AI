-- CEOPRO AI - Video-post metadata columns.
-- video_transcript_provider.py fetches a competitor video's view count,
-- creator handle, and original publish date alongside its transcript, but
-- market_observations had nowhere to hold them (like_count/share_count
-- already exist from 20260906010000_add_engagement_metrics_columns.sql,
-- content_date/creator_handle/view_count do not). Nullable throughout:
-- every existing collector has nothing to report here and keeps working
-- unchanged.

ALTER TABLE market_observations
    ADD COLUMN IF NOT EXISTS view_count INT CHECK (view_count >= 0),
    ADD COLUMN IF NOT EXISTS creator_handle TEXT,
    ADD COLUMN IF NOT EXISTS content_date TIMESTAMP WITH TIME ZONE;
