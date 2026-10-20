-- Undoes migrations/20261026010000_add_comments_refresh_function.sql. The worker's daily comments sweep then logs
-- an error and skips (it never stops the rest of the sweep); comments are simply no longer refreshed automatically.
DROP FUNCTION IF EXISTS list_tenants_with_due_comments_refresh(INT);
