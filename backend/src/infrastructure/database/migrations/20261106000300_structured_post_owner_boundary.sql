-- Narrow direct-write authority on append-only posting evidence as well as HTTP guards.
ALTER POLICY structured_post_tenant ON public.keel_structured_import_posts
 WITH CHECK(tenant_id=public.get_current_tenant()
 AND actor_id=nullif(current_setting('app.current_user_id',true),'')::uuid
 AND EXISTS(SELECT 1 FROM public.tenant_users u WHERE u.tenant_id=keel_structured_import_posts.tenant_id AND u.user_id=keel_structured_import_posts.actor_id AND u.role_key IN('owner','admin') AND u.removed_at IS NULL AND u.platform_suspended_at IS NULL)
 AND EXISTS(SELECT 1 FROM public.keel_import_batches b WHERE b.tenant_id=keel_structured_import_posts.tenant_id AND b.batch_id=keel_structured_import_posts.batch_id AND b.created_by_user_id=keel_structured_import_posts.actor_id));
