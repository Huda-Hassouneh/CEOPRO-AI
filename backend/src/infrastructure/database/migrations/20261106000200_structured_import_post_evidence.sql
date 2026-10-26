CREATE TABLE public.keel_structured_import_posts(
 tenant_id uuid NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,batch_id uuid NOT NULL,
 actor_id uuid NOT NULL REFERENCES users(user_id),request_hash char(64) NOT NULL,response jsonb NOT NULL,evidence jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),PRIMARY KEY(tenant_id,batch_id),FOREIGN KEY(tenant_id,batch_id) REFERENCES keel_import_batches(tenant_id,batch_id) ON DELETE CASCADE);
ALTER TABLE public.keel_structured_import_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.keel_structured_import_posts FORCE ROW LEVEL SECURITY;
CREATE POLICY structured_post_tenant ON public.keel_structured_import_posts TO ceopro_app USING(tenant_id=public.get_current_tenant()) WITH CHECK(tenant_id=public.get_current_tenant() AND actor_id=nullif(current_setting('app.current_user_id',true),'')::uuid);
REVOKE ALL ON public.keel_structured_import_posts FROM PUBLIC,ceopro_app;
GRANT SELECT,INSERT ON public.keel_structured_import_posts TO ceopro_app;
