-- CEOPRO AI - RAG Business Copilot Phase 2: conversation persistence.
--
-- Closes a real, previously-documented gap (RAG_BUSINESS_COPILOT_
-- ARCHITECTURE.md's own "what this pass deliberately did not build" list):
-- conversation history existed only as caller-supplied JSON per request
-- (rag/llm_client.py's `history` param, sent from the frontend's own local
-- React state) - nothing survived a page refresh or a new device/session.
--
-- Two tables, same tenant-isolation convention as every other table here
-- (get_current_tenant(), FORCE ROW LEVEL SECURITY) - PLUS an explicit
-- user_id check in both policies, stronger than most other tables in this
-- schema: a conversation is a specific person's chat, not shared company
-- data the way products/competitors are, so tenant membership alone isn't
-- the right isolation boundary here - RLS enforces "this session belongs to
-- the exact authenticated user asking", not just "someone at this company".
--
-- No secrets are stored here: `content` is the literal chat text (same
-- content the user already typed/read in their own browser), `sources` is
-- the same citation metadata /rag/query already returns to the client today
-- (chunk_id/score or url/title) - nothing new is captured, only persisted.

CREATE TABLE IF NOT EXISTS conversation_sessions (
    session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    -- First user message, truncated - a real, cheap session title for a
    -- future session-list UI, never LLM-generated (no extra cost/call).
    title TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp(),
    CONSTRAINT uq_tenant_session_perimeter UNIQUE (tenant_id, session_id)
);

CREATE INDEX IF NOT EXISTS idx_conversation_sessions_tenant_user ON conversation_sessions(tenant_id, user_id, updated_at DESC);

ALTER TABLE conversation_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_sessions FORCE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'conversation_sessions' AND policyname = 'isolation_conversation_sessions') THEN
        CREATE POLICY isolation_conversation_sessions ON conversation_sessions FOR ALL
            USING (tenant_id = get_current_tenant() AND user_id = current_setting('app.current_user_id', true)::uuid);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS conversation_messages (
    message_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- A real monotonic ordering column, deliberately NOT relying on
    -- created_at alone for ORDER BY: Postgres's CURRENT_TIMESTAMP is
    -- frozen at transaction start (the SAME value for every statement in
    -- one transaction), and a single /rag/query request writes the user
    -- message and the assistant's answer in one transaction - both would
    -- get an identical created_at, making "which came first" ambiguous.
    -- clock_timestamp() below (real wall-clock time per call) already
    -- fixes that for created_at's own display value, but seq is the
    -- actual ORDER BY key everywhere ordering matters - a BIGSERIAL is
    -- guaranteed strictly increasing in insertion order, no timestamp-
    -- resolution edge case possible.
    seq BIGSERIAL,
    tenant_id UUID NOT NULL,
    session_id UUID NOT NULL,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    role VARCHAR(10) NOT NULL CONSTRAINT chk_conversation_messages_role CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    -- The same sources array /rag/query already returns (chunk citations
    -- and/or web-fallback sources) - stored verbatim, never re-derived.
    sources JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp(),
    CONSTRAINT fk_conversation_messages_session_isolated FOREIGN KEY (tenant_id, session_id)
        REFERENCES conversation_sessions(tenant_id, session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_conversation_messages_session ON conversation_messages(tenant_id, session_id, seq ASC);

ALTER TABLE conversation_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_messages FORCE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'conversation_messages' AND policyname = 'isolation_conversation_messages') THEN
        CREATE POLICY isolation_conversation_messages ON conversation_messages FOR ALL
            USING (tenant_id = get_current_tenant() AND user_id = current_setting('app.current_user_id', true)::uuid);
    END IF;
END $$;
