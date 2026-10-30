"""Read-only owner-policy/document/source checks. No network, DB or source writes."""
from pathlib import Path
import argparse, collections, hashlib, json, re, subprocess

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--python-root', required=True)
    ap.add_argument('--node-root', required=True)
    ap.add_argument('--write-result', action='store_true')
    a = ap.parse_args()
    p, n = Path(a.python_root).resolve(), Path(a.node_root).resolve()
    d = p/'docs/keel-integration'
    e = d/'evidence/owner-decisions'
    errors = []
    def check(condition, message):
        if not condition:
            errors.append(message)
    data = json.loads((e/'OWNER_SELECTIONS.json').read_text())
    source = d/data['source_path']
    check(sha(source) == data['source_sha256'], 'owner register hash mismatch')
    decisions = re.findall(r'^### ([A-Z]+-\d+) — ([^\n]+)\n(.*?)(?=^### |^## |\Z)',source.read_text(), re.M|re.S)
    check(len(decisions) == 13, 'owner decision count')
    records = {x['decision_id']:x for x in data['records']}
    check(len(records) == 13 and set(records) == {x[0] for x in decisions}, 'decision IDs differ')
    worksheet = (d/'OWNER_DECISION_WORKSHEET.md').read_text()
    index = (d/'DECISION_REGISTER.md').read_text()
    for key,title,body in decisions:
        x = records[key]
        adr = (d/x['adr_path']).read_text()
        check(body.strip() == x['approved_text'], key+' structured selection mismatch')
        check(body.strip() in adr and body.strip() in worksheet, key+' exact policy omitted')
        check(x['pending_details'] in adr and x['pending_details'] in worksheet, key+' pending details omitted')
        check('OWNER POLICY SELECTED' in adr and 'Implementation permission: NOT GRANTED' in adr and 'Production release permission: NOT GRANTED' in adr,key+' permission/state mismatch')
        check('Owner selection: **UNRESOLVED**' not in adr and 'owner decision pending' not in adr and 'Approval remains **PENDING**' not in adr,key+' stale approval state')
        check(x['policy_status']=='SELECTED' and x['approval_date']=='2026-10-20' and x['implementation_authorized'] is False and x['release_authorized'] is False,key+' incorrect status')
        check('['+key+']('+x['adr_path']+')' in index,key+' missing decision index')
    manifest = json.loads((d/'evidence/SUPPLIED_CONTENT_HASHES.json').read_text())
    integrity = {}
    for repo,root in [('python',p),('node',n)]:
        bad = [k for k,v in manifest[repo].items() if not(root/k).is_file() or sha(root/k)!=v]
        check(not bad, repo+' original source changed')
        integrity[repo] = {'original_files':len(manifest[repo]),'changed_or_missing':bad}
    head = subprocess.check_output(['git','-C',str(p),'rev-parse','HEAD'],text=True).strip()
    check(head=='1de393c77dfc6db9d8722d8a611d2384d64d12c0','HEAD changed')
    baseline = json.loads((e/'DOCUMENT_BASELINE_OWNER_RECONCILIATION.json').read_text())
    current = {'docs/keel-integration/'+str(f.relative_to(d)):sha(f) for f in d.rglob('*') if f.is_file() and '__pycache__' not in f.parts}
    changes = {k:('ADD' if k not in baseline else 'MODIFY') for k,v in current.items() if k not in baseline or v!=baseline[k]}
    changes.update({k:'DELETE' for k in baseline if k not in current})
    ledger = (d/'UNIFIED_FILE_CHANGE_LEDGER.md').read_text()
    entries = dict(re.findall(r'^\| 0R-OWNER \| [^|]*\| `([^`]+)` \| (ADD|MODIFY|DELETE|RENAME) \|',ledger,re.M))
    check(entries==changes,'owner incremental ledger mismatch')
    registered = set(re.findall(r'^\| (?:0|0R|0R-OWNER) \| [^|]*\| `([^`]+)` \| (?:ADD|MODIFY|DELETE|RENAME) \|',ledger,re.M))
    check(registered == set(current), 'cumulative ledger inventory mismatch')
    git_paths = set(subprocess.check_output(['git','-C',str(p),'ls-files','--others','--exclude-standard','docs/keel-integration'],text=True).splitlines())
    git_paths |= set(subprocess.check_output(['git','-C',str(p),'ls-files','docs/keel-integration'],text=True).splitlines())
    check(git_paths == set(current),'actual Git document inventory mismatch')
    recorded = {path:op for op,path in re.findall(r'^(ADD|MODIFY|DELETE|RENAME)\t(.+)$',(e/'GIT_DOCUMENT_DIFF_OWNER_RECONCILIATION.txt').read_text(),re.M)}
    check(recorded == changes,'Git no-index diff mismatch')
    extra = [k for k in subprocess.check_output(['git','-C',str(p),'ls-files','--others','--exclude-standard'],text=True).splitlines() if not k.startswith('docs/keel-integration/') and k not in manifest['python']]
    check(not extra,'new non-document source files')
    broken = []
    for f in d.rglob('*.md'):
        if 'reference' in f.relative_to(d).parts:
            continue
        for link in re.findall(r'\]\(([^)]+)\)',f.read_text()):
            target=link.split('#')[0]
            if target and not re.match(r'\w+:|^/',target) and not(f.parent/target).exists():
                broken.append(str(f.relative_to(d))+': '+link)
    check(not broken,'broken relative document links')
    result = {'phase':'0R-OWNER','result':'PASS' if not errors else 'FAIL','owner_policies_selected':len(records),'implementation_authorized':False,'production_release_authorized':False,'pending_details':'Retained per decision; no numeric/legal/operational values inferred','source_integrity':integrity,'head':head,'document_files':len(current),'incremental_operations':dict(collections.Counter(changes.values())),'ledger_matches_actual_document_changes':entries==changes,'git_no_index_diff_matches':recorded==changes,'actual_git_document_inventory_matches':git_paths==set(current),'new_non_document_python_files':extra,'broken_relative_links':broken,'production_tests':'NOT RUN; documentation-only reconciliation','native_and_provider_gates':'UNCHANGED / NOT CERTIFIED','errors':errors}
    if a.write_result:
        (e/'OWNER_RECONCILIATION_VERIFICATION.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    return 1 if errors else 0

if __name__ == '__main__':
    raise SystemExit(main())
