-- Associate a metered operation with one user's RAG turn and execution fence.
ALTER TABLE public.billing_logical_operations ADD COLUMN IF NOT EXISTS actor_user_id UUID;
GRANT INSERT (actor_user_id) ON public.billing_logical_operations TO ceopro_credit_accounting;
CREATE UNIQUE INDEX IF NOT EXISTS billing_logical_operations_actor_identity
    ON public.billing_logical_operations (tenant_id, id, actor_user_id);

CREATE OR REPLACE FUNCTION public.billing_logical_operation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.logical_operation_id IS DISTINCT FROM OLD.logical_operation_id
       OR NEW.operation_kind IS DISTINCT FROM OLD.operation_kind
       OR NEW.input_fingerprint IS DISTINCT FROM OLD.input_fingerprint
       OR NEW.actor_user_id IS DISTINCT FROM OLD.actor_user_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'logical operation identity is immutable';
    END IF;
    IF OLD.status <> 'in_progress' AND NEW.status IS DISTINCT FROM OLD.status THEN
        RAISE EXCEPTION 'logical operation is already terminal';
    END IF;
    RETURN NEW;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS conversation_sessions_user_identity
    ON public.conversation_sessions (tenant_id, user_id, session_id);
CREATE UNIQUE INDEX IF NOT EXISTS conversation_messages_user_identity
    ON public.conversation_messages (tenant_id, user_id, session_id, message_id);

CREATE TABLE IF NOT EXISTS public.rag_logical_requests (
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    operation_ref UUID NOT NULL,
    session_id UUID,
    user_message_id UUID,
    assistant_message_id UUID,
    conversation_state JSONB,
    state TEXT NOT NULL DEFAULT 'preparing' CHECK (state IN ('preparing','provider_started','completed','failed')),
    lease_owner UUID,
    lease_expires_at TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, operation_ref),
    FOREIGN KEY (tenant_id, operation_ref, user_id)
        REFERENCES public.billing_logical_operations (tenant_id, id, actor_user_id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, user_id, session_id)
        REFERENCES public.conversation_sessions (tenant_id, user_id, session_id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, user_id, session_id, user_message_id)
        REFERENCES public.conversation_messages (tenant_id, user_id, session_id, message_id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, user_id, session_id, assistant_message_id)
        REFERENCES public.conversation_messages (tenant_id, user_id, session_id, message_id) ON DELETE CASCADE,
    CHECK ((lease_owner IS NULL) = (lease_expires_at IS NULL)),
    CHECK (user_message_id IS NULL OR session_id IS NOT NULL),
    CHECK (assistant_message_id IS NULL OR user_message_id IS NOT NULL),
    CHECK (state IN ('preparing','failed') OR user_message_id IS NOT NULL),
    CHECK ((state = 'completed') = (assistant_message_id IS NOT NULL))
);
ALTER TABLE public.rag_logical_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rag_logical_requests FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rag_logical_requests_owner ON public.rag_logical_requests;
CREATE POLICY rag_logical_requests_owner ON public.rag_logical_requests TO ceopro_app
    USING (tenant_id = public.get_current_tenant() AND user_id = nullif(current_setting('app.current_user_id', true), '')::uuid)
    WITH CHECK (tenant_id = public.get_current_tenant() AND user_id = nullif(current_setting('app.current_user_id', true), '')::uuid);
REVOKE ALL ON public.rag_logical_requests FROM PUBLIC, ceopro_app;
GRANT SELECT, INSERT (tenant_id, user_id, operation_ref),
    UPDATE (session_id, user_message_id, assistant_message_id, conversation_state, state, lease_owner, lease_expires_at)
    ON public.rag_logical_requests TO ceopro_app;

CREATE OR REPLACE FUNCTION public.rag_logical_request_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR NEW.user_id IS DISTINCT FROM OLD.user_id
       OR NEW.operation_ref IS DISTINCT FROM OLD.operation_ref
       OR (OLD.session_id IS NOT NULL AND NEW.session_id IS DISTINCT FROM OLD.session_id)
       OR (OLD.user_message_id IS NOT NULL AND NEW.user_message_id IS DISTINCT FROM OLD.user_message_id)
       OR (OLD.user_message_id IS NOT NULL AND NEW.conversation_state IS DISTINCT FROM OLD.conversation_state)
       OR (OLD.assistant_message_id IS NOT NULL AND NEW.assistant_message_id IS DISTINCT FROM OLD.assistant_message_id)
       OR (OLD.state = 'provider_started' AND NEW.state NOT IN ('provider_started','completed'))
       OR (OLD.state = 'failed' AND NEW.state <> 'failed')
       OR (OLD.state = 'completed' AND NEW.state <> 'completed') THEN
        RAISE EXCEPTION 'RAG request identity or execution state cannot be rewritten';
    END IF;
    IF NEW.user_message_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.conversation_messages m WHERE m.tenant_id=NEW.tenant_id
          AND m.user_id=NEW.user_id AND m.session_id=NEW.session_id
          AND m.message_id=NEW.user_message_id AND m.role='user'
    ) THEN
        RAISE EXCEPTION 'RAG request requires its own user message';
    END IF;
    IF NEW.assistant_message_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.conversation_messages m WHERE m.tenant_id=NEW.tenant_id
          AND m.user_id=NEW.user_id AND m.session_id=NEW.session_id
          AND m.message_id=NEW.assistant_message_id AND m.role='assistant'
    ) THEN
        RAISE EXCEPTION 'RAG request requires its own assistant message';
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS rag_logical_request_guard ON public.rag_logical_requests;
CREATE TRIGGER rag_logical_request_guard BEFORE UPDATE ON public.rag_logical_requests
    FOR EACH ROW EXECUTE FUNCTION public.rag_logical_request_guard();
