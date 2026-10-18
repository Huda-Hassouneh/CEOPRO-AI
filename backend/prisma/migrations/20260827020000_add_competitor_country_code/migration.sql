-- CEOPRO AI - Restore competitor country context.
-- Final_schema.sql's global_competitors has no country_code at all (nor any
-- equivalent) - src/ai/mpi/data_access.py's load_country_context() needs it
-- for COMPETITOR-subject MPI computations (spec S4 Global/Country-Aware
-- Architecture, spec S17). Nullable, same as the old schema - not every
-- competitor's country is known.

ALTER TABLE global_competitors ADD COLUMN IF NOT EXISTS country_code VARCHAR(2);
