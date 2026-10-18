ALTER TABLE public.rag_document_search ADD COLUMN source_text text NOT NULL DEFAULT '';
ALTER TABLE public.rag_document_search ADD COLUMN source_revision text NOT NULL DEFAULT '';

CREATE TABLE public.rag_chat_sessions (
  tenant_id uuid NOT NULL, user_id uuid NOT NULL, session_id uuid NOT NULL,
  title varchar(100) NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(tenant_id,user_id,session_id),
  FOREIGN KEY(tenant_id,user_id) REFERENCES public.tenant_users(tenant_id,user_id) ON DELETE CASCADE
);
-- Tenant billing metadata only: no prompts, answers or document contents.
CREATE TABLE public.rag_token_reservations (
  tenant_id uuid NOT NULL, user_id uuid NOT NULL, request_id uuid NOT NULL,
  usage_record_id uuid NOT NULL REFERENCES public.subscription_usage(id) ON DELETE CASCADE,
  reserved_tokens integer NOT NULL CHECK(reserved_tokens>0),
  allocation_limit integer CHECK(allocation_limit>=0),
  billed_tokens integer NOT NULL DEFAULT 0 CHECK(billed_tokens>=0),
  status text NOT NULL CHECK(status IN ('pending','settled','released')),
  expires_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(tenant_id,user_id,request_id),
  FOREIGN KEY(tenant_id,user_id) REFERENCES public.tenant_users(tenant_id,user_id) ON DELETE CASCADE
);
CREATE INDEX idx_rag_reservation_expiry ON public.rag_token_reservations(tenant_id,expires_at) WHERE status='pending';
CREATE TABLE public.rag_chat_requests (
  tenant_id uuid NOT NULL, user_id uuid NOT NULL, request_id uuid NOT NULL, session_id uuid NOT NULL,
  request_hash char(64) NOT NULL, question text NOT NULL,
  status text NOT NULL CHECK(status IN ('pending','completed','failed')),
  response jsonb, failure_code text, created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(tenant_id,user_id,request_id),
  FOREIGN KEY(tenant_id,user_id,session_id) REFERENCES public.rag_chat_sessions(tenant_id,user_id,session_id) ON DELETE CASCADE,
  FOREIGN KEY(tenant_id,user_id,request_id) REFERENCES public.rag_token_reservations(tenant_id,user_id,request_id) ON DELETE CASCADE
);
CREATE INDEX idx_rag_chat_session_turns ON public.rag_chat_requests(tenant_id,user_id,session_id,created_at);

ALTER TABLE public.rag_chat_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rag_chat_sessions FORCE ROW LEVEL SECURITY;
ALTER TABLE public.rag_chat_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rag_chat_requests FORCE ROW LEVEL SECURITY;
ALTER TABLE public.rag_token_reservations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rag_token_reservations FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.rag_chat_sessions,public.rag_chat_requests,public.rag_token_reservations FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.rag_chat_sessions,public.rag_chat_requests TO ceopro_app;
GRANT SELECT,INSERT,UPDATE ON public.rag_token_reservations TO ceopro_app;
CREATE POLICY rag_chat_sessions_private ON public.rag_chat_sessions TO ceopro_app
  USING(tenant_id=public.get_current_tenant() AND user_id=nullif(current_setting('app.current_user_id',true),'')::uuid)
  WITH CHECK(tenant_id=public.get_current_tenant() AND user_id=nullif(current_setting('app.current_user_id',true),'')::uuid);
CREATE POLICY rag_chat_requests_private ON public.rag_chat_requests TO ceopro_app
  USING(tenant_id=public.get_current_tenant() AND user_id=nullif(current_setting('app.current_user_id',true),'')::uuid)
  WITH CHECK(tenant_id=public.get_current_tenant() AND user_id=nullif(current_setting('app.current_user_id',true),'')::uuid);
CREATE POLICY rag_reservations_tenant ON public.rag_token_reservations TO ceopro_app
  USING(tenant_id=public.get_current_tenant())
  WITH CHECK(tenant_id=public.get_current_tenant() AND EXISTS(
    SELECT 1 FROM public.subscription_usage usage
    JOIN public.subscriptions subscription ON subscription.id=usage.subscription_id
    JOIN public.features feature ON feature.feature_id=usage.feature_id
    WHERE usage.id=rag_token_reservations.usage_record_id
      AND subscription.tenant_id=rag_token_reservations.tenant_id
      AND feature.feature_code='rag_assistant'
  ));
