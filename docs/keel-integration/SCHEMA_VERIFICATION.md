# Source-verified schema lineage — Phase 0R

The authoritative mapping for this phase is **source-verified DDL and Prisma schema**, not the earlier lexical candidates and not an executed PostgreSQL catalog. No database was contacted or migration run. Every feature family has a separate `SCHEMA_LINEAGE_<FAMILY>.csv` under evidence/phase0r/.

## Verification levels

| Evidence level | What was established | What was not established |
|---|---|---|
| SOURCE_DDL_VERIFIED_NATIVE_PENDING | Parsed actual CREATE/ALTER TABLE, column, constraint/index, policy/function/trigger and privilege statements at exact source paths/lines | Effective deployed state, migration application, owner OID/role membership, runtime privileges or PG17 execution |
| CONDITIONAL_DDL_SOURCE_NATIVE_PENDING | Literal DDL present inside a conditional DO body | Which branch executes, object already existing, role existence or resulting policy |
| DYNAMIC_SQL_RLS_OR_DDL | Exact EXECUTE/format/loop location and script body retained as an obligation | Expanded runtime policy/grants and actual catalog objects |
| PRISMA mapping | Model/delegate/field → explicit mapped table/column from schema.prisma, with real SQL table identity cross-check | Generated SQL shape for every relation include, or effective migration correctness |
| SQL access source fact | A table reference/ORM delegate in a selected or transitive body matches an actual CREATE TABLE identity | Execution of that branch, valid SQL arguments or successful row write |

The parser accepted both schemas and every migration file without a grammar parse error; extractor records 174 table identities across both repositories, 4,241 DDL-object records and 1,877 column operations. These are source-history records, not counts of distinct live tables/columns. The parser was pglast 8.7 with PostgreSQL 18 grammar; it is a discovery/structure tool and **cannot certify PostgreSQL 17 compatibility**. Native PG17 rehearsal remains VERIFY-001.

`SCHEMA_DDL_OBJECTS.csv` includes exact table, column constraints, named/unnamed table constraints, indexes/partial indexes, RLS policies, functions, triggers, GRANT/REVOKE and later alteration/drop history. `SCHEMA_COLUMNS.csv` retains source ordering and CREATE/ALTER operation rather than pretending a dropped column still exists. Per-feature lineage includes the relevant table records and shared get_current_tenant/auth/bootstrap boundaries. Schema-owning role and PUBLIC/ceopro_app/service grants are source statements; effective owners must be queried in native catalogs.

`DYNAMIC_SQL_OBLIGATIONS.csv` retains 23 conditional EXECUTE/format obligations. A loop template can clearly name store_tenant/isolation policies and role grants, but source expansion alone does not establish that it executed. Do not use a template string as proof of an effective policy. Native verification must expand and match these records.

## Required native closure

In a dedicated disposable PG17 cluster, run existing migration runner on empty and populated historical copies, then repeat. Export pg_class/pg_attribute/pg_constraint/pg_index/pg_policy/pg_proc/pg_trigger, table/function owners, ACLs and runtime role membership; compare to source in actual migration order. Confirm ceopro_app NOSUPERUSER/NOBYPASSRLS by password login, FORCE RLS and wrong-tenant read/write/lookup, auth recursion fix, lookup function search_path and service-principal exception. Test concurrent seat/source/product/usage/promo/quote/webhook writes and crash/receipt release invariants. Never supply a production DSN or bypass the existing guarded fixture validation.

The earlier raw db_objects strings, including fastapi/typing/src.ai, are preserved **verbatim** in RAW_PHASE0_DB_CANDIDATES.csv and remain nonauthoritative. Cleaned CAPABILITY_TRACEABILITY.db_objects now contains only repo-qualified table identities confirmed in DDL; it is a source-access join, not the effective catalog.
