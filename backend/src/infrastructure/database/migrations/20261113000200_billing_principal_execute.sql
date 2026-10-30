-- The constrained membership-lock/schedule function owner must be able to
-- call the existing active-principal predicate; no new membership writes.
GRANT EXECUTE ON FUNCTION public.keel_active_principal(uuid,uuid) TO ceopro_schedule_writer;
