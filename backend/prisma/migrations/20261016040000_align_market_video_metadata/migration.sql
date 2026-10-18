-- Import the AI team's existing 20260913010000_add_video_metadata_columns.sql
-- contract into Prisma's forward migration history. Optional for ordinary prices.
-- No data rewrite, authorization change, or collector behavior change.
ALTER TABLE public.market_observations
    ADD COLUMN IF NOT EXISTS view_count INT CHECK (view_count >= 0),
    ADD COLUMN IF NOT EXISTS creator_handle TEXT,
    ADD COLUMN IF NOT EXISTS content_date TIMESTAMP WITH TIME ZONE;
