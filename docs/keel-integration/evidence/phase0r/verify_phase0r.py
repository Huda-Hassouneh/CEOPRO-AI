"""Read-only Phase 0R source/document checks; optional JSON output is docs-only.

Run with --python-root and --node-root. No DB, network, providers or source edits.
"""
from pathlib import Path
import argparse, collections, csv, hashlib, json, re, subprocess

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--python-root', required=True)
    ap.add_argument('--node-root', required=True)
    ap.add_argument('--write-result', action='store_true')
    a = ap.parse_args()
    p, n = Path(a.python_root).resolve(), Path(a.node_root).resolve()
    d, errors = p / 'docs/keel-integration', []
    r = d / 'evidence/phase0r'
    def check(condition, message):
        if not condition:
            errors.append(message)
    def table(path):
        return list(csv.DictReader((d / path).open()))
    manifest = json.loads((d / 'evidence/SUPPLIED_CONTENT_HASHES.json').read_text())
    integrity = {}
    for repo, root in [('python', p), ('node', n)]:
        changed = [k for k,v in manifest[repo].items() if not (root/k).is_file() or sha(root/k) != v]
        integrity[repo] = {'original_files': len(manifest[repo]), 'changed_or_missing': changed}
        check(not changed, f'{repo} original content changed')
    head = subprocess.check_output(['git','-C',str(p),'rev-parse','HEAD'], text=True).strip()
    check(head == '1de393c77dfc6db9d8722d8a611d2384d64d12c0', 'HEAD changed')
    caps = table('CAPABILITY_TRACEABILITY.csv')
    business = [x for x in caps if x['domain'] != 'GOVERNANCE']
    ids = {x['capability_id'] for x in business}
    check(len(caps) == len({x['capability_id'] for x in caps}) == 129, 'capability identifiers')
    check(len(business) == 125, 'business count')
    baseline_ids = {x['capability_id'] for x in table('evidence/phase0r/RAW_PHASE0_DB_CANDIDATES.csv')}
    check(ids <= baseline_ids, 'business identifiers differ from historical raw registry')
    at = table('evidence/ACCEPTANCE_TEST_SPEC.csv')
    check(len(at) == len({x['test_id'] for x in at}) == 125, 'acceptance identifiers')
    check({x['test_id'] for x in business} == {x['test_id'] for x in at}, 'acceptance mapping')
    for x in business:
        check(all('domain-source fallback' not in x[k].lower() for k in ['node_evidence','python_evidence']), 'fallback '+x['capability_id'])
    check(len(table('FEATURE_AND_ENTITLEMENT_CROSSWALK.csv')) == 24, 'feature mapping count')
    flows = table('evidence/phase0r/ATOMIC_FLOW_TRACES.csv')
    check(len(flows) == len({(x['capability_id'],x['repo']) for x in flows}) == 250, 'atomic flow pairs')
    refs = table('evidence/phase0r/SOURCE_FUNCTION_REFERENCES.csv')
    bad_refs = []
    source_line_counts = {}
    for x in refs:
        match = re.match(r'(.+?):(\d+)(?::\d+)?::', x['source'])
        root = p if x['repo'] == 'python' else n
        if not match or not (root/match[1]).is_file():
            bad_refs.append(x['source'])
        else:
            path = root/match[1]
            if path not in source_line_counts:
                source_line_counts[path] = len(path.read_text(errors='replace').splitlines())
            if int(match[2]) > source_line_counts[path]:
                bad_refs.append(x['source'])
    check(not bad_refs, 'missing function source references')
    ddl = table('evidence/phase0r/SCHEMA_DDL_OBJECTS.csv')
    real_tables = {(x['repo'],x['object_name']) for x in ddl if x['object_kind'] == 'TABLE'}
    # Some table rows use table_name as their normalized identity.
    real_tables |= {(x['repo'],x['table_name']) for x in ddl if x['object_kind'] == 'TABLE'}
    bad_objects = []
    for x in business:
        for token in re.split(r'\s*[;|]\s*',x['db_objects']):
            if token:
                repo, obj = token.split(':',1)
                if (repo,obj) not in real_tables:
                    bad_objects.append(token)
    check(not bad_objects, 'non-DDL canonical schema identity')
    check(len(list(r.glob('SCHEMA_LINEAGE_*.csv'))) == 14, 'schema family count')
    dynamic = table('evidence/phase0r/DYNAMIC_SQL_OBLIGATIONS.csv')
    check(len(dynamic) == 23, 'dynamic SQL obligations lost')
    worksheet = (d/'OWNER_DECISION_WORKSHEET.md').read_text()
    check(worksheet.count('Approval status: **PENDING**') == 13, 'owner approval state')
    readiness = table('evidence/phase0r/DOMAIN_READINESS.csv')
    check(len(readiness) == 14 and all(x['implementation_status']=='BLOCKED' for x in readiness), 'implementation gate lost')
    # Historical/reference documents can contain external-original relative links.
    broken = []
    for f in d.rglob('*.md'):
        if 'reference' in f.relative_to(d).parts:
            continue
        for link in re.findall(r'\]\(([^)]+)\)',f.read_text()):
            target = link.split('#')[0]
            if target and not re.match(r'\w+:|^/',target) and not (f.parent/target).exists():
                broken.append(f'{f.relative_to(d)}: {link}')
    check(not broken, 'broken relative document links')
    baseline = json.loads((r/'DOCUMENT_BASELINE_PHASE0R.json').read_text())
    current = {'docs/keel-integration/'+str(f.relative_to(d)):sha(f) for f in d.rglob('*') if f.is_file() and '__pycache__' not in f.parts}
    changes = {k:('ADD' if k not in baseline else 'MODIFY') for k,v in current.items() if k not in baseline or baseline[k]!=v}
    changes.update({k:'DELETE' for k in baseline if k not in current})
    ledger = (d/'UNIFIED_FILE_CHANGE_LEDGER.md').read_text()
    entries = dict(re.findall(r'^\| 0R \| [^|]*\| `([^`]+)` \| (ADD|MODIFY|DELETE|RENAME) \|',ledger,re.M))
    check(entries == changes, 'incremental ledger does not reconcile')
    historic = set(re.findall(r'^\| 0 \| [^|]*\| `([^`]+)` \| ADD \|',ledger,re.M))
    check(historic == set(baseline), 'historical ledger changed')
    git_paths = set(subprocess.check_output(['git','-C',str(p),'ls-files','--others','--exclude-standard','docs/keel-integration'],text=True).splitlines())
    tracked_doc_paths = set(subprocess.check_output(['git','-C',str(p),'ls-files','docs/keel-integration'],text=True).splitlines())
    check(git_paths|tracked_doc_paths == set(current), 'actual Git documentation inventory mismatch')
    recorded_diff = dict(re.findall(r'^(ADD|MODIFY|DELETE|RENAME)\t(.+)$',(r/'GIT_DOCUMENT_DIFF_PHASE0R.txt').read_text(),re.M))
    # Build path -> operation, including all repeated operation types.
    recorded_diff = {path:op for op,path in re.findall(r'^(ADD|MODIFY|DELETE|RENAME)\t(.+)$',(r/'GIT_DOCUMENT_DIFF_PHASE0R.txt').read_text(),re.M)}
    check(recorded_diff == changes, 'git no-index diff path/action mismatch')
    allowed_source = set(manifest['python'])
    untracked = subprocess.check_output(['git','-C',str(p),'ls-files','--others','--exclude-standard'],text=True).splitlines()
    extra = [k for k in untracked if not k.startswith('docs/keel-integration/') and k not in allowed_source]
    check(not extra, 'new non-document Python files')
    result = {'phase':'0R','result':'PASS' if not errors else 'FAIL','source_integrity':integrity,'head':head,'capabilities':len(caps),'business_capabilities':len(business),'atomic_repo_traces':len(flows),'function_source_references':len(refs),'schema_source_records':len(ddl),'dynamic_sql_native_obligations':len(dynamic),'pending_owner_decisions':13,'document_files':len(current),'incremental_operations':dict(collections.Counter(changes.values())),'ledger_matches':entries==changes,'actual_git_document_inventory_matches':git_paths|tracked_doc_paths==set(current),'git_no_index_name_status_matches':recorded_diff==changes,'missing_source_references':bad_refs,'invalid_schema_identities':bad_objects,'broken_relative_links':broken,'new_non_document_python_files':extra,'native_postgres_tests':'NOT RUN','live_provider_tests':'NOT RUN','runtime_integration_acceptance':'NOT RUN','phase1_authorized':False,'errors':errors}
    if a.write_result:
        (r/'PHASE0R_VERIFICATION.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    return 1 if errors else 0

if __name__ == '__main__':
    raise SystemExit(main())
