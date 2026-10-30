"""Read-only Phase 0V provenance/document check, never a native DB certificate."""
from pathlib import Path
import argparse, collections, csv, hashlib, json, re, subprocess
import xml.etree.ElementTree as XML

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--python-root',required=True)
    ap.add_argument('--node-root',required=True)
    ap.add_argument('--write-result',action='store_true')
    a=ap.parse_args()
    p,n=Path(a.python_root).resolve(),Path(a.node_root).resolve()
    d=p/'docs/keel-integration';e=d/'evidence/phase0v';errors=[]
    def check(condition,message):
        if not condition:errors.append(message)
    before=json.loads((e/'DOCUMENT_BASELINE_PHASE0V.json').read_text())
    manifest=json.loads((d/'evidence/SUPPLIED_CONTENT_HASHES.json').read_text())
    pre=json.loads((e/'SOURCE_BASELINE_PREFLIGHT.json').read_text())
    integrity={}
    for repo,root in [('python',p),('node',n)]:
        bad=[k for k,v in manifest[repo].items()if not(root/k).is_file()or sha(root/k)!=v]
        check(not bad,repo+' original files changed')
        integrity[repo]={'files':len(manifest[repo]),'changed_or_missing':bad}
    head=subprocess.check_output(['git','-C',str(p),'rev-parse','HEAD'],text=True).strip()
    check(head==pre['head']=='1de393c77dfc6db9d8722d8a611d2384d64d12c0','source HEAD mismatch')
    check(not subprocess.check_output(['git','-C',str(p),'diff','--cached','--binary']),'staged changes introduced')
    own=json.loads((d/'evidence/owner-decisions/OWNER_SELECTIONS.json').read_text())
    check(len(own['records'])==13,'owner policy count')
    check(sha(d/own['source_path'])==own['source_sha256'],'owner register modified')
    for x in own['records']:
        adr=d/x['adr_path']
        check(x['approved_text'] in adr.read_text() and x['approved_text'] in (d/'OWNER_DECISION_WORKSHEET.md').read_text(),x['decision_id']+' exact selection mismatch')
        check(x['pending_details'] in adr.read_text(),x['decision_id']+' pending details lost')
        check(sha(adr)==before['docs/keel-integration/'+x['adr_path']],x['decision_id']+' already reconciled ADR unnecessarily changed')
        check(x['implementation_authorized'] is False and x['release_authorized'] is False,'permission changed')
    current={'docs/keel-integration/'+str(f.relative_to(d)):sha(f)for f in d.rglob('*')if f.is_file()and'__pycache__'not in f.parts}
    changes={k:('ADD'if k not in before else'MODIFY')for k,v in current.items()if k not in before or v!=before[k]}
    changes.update({k:'DELETE'for k in before if k not in current})
    ledger=(d/'UNIFIED_FILE_CHANGE_LEDGER.md').read_text()
    rows=dict(re.findall(r'^\| 0V \| [^|]*\| `([^`]+)` \| (ADD|MODIFY|DELETE|RENAME) \|',ledger,re.M))
    check(rows==changes,'Phase 0V ledger mismatch')
    cumulative=set(re.findall(r'^\| (?:0|0R|0R-OWNER|0V) \| [^|]*\| `([^`]+)` \| (?:ADD|MODIFY|DELETE|RENAME) \|',ledger,re.M))
    check(cumulative==set(current),'cumulative ledger inventory mismatch')
    actual=set(subprocess.check_output(['git','-C',str(p),'ls-files','--others','--exclude-standard','docs/keel-integration'],text=True).splitlines())
    actual|=set(subprocess.check_output(['git','-C',str(p),'ls-files','docs/keel-integration'],text=True).splitlines())
    check(actual==set(current),'actual Git doc inventory mismatch')
    diff={path:op for op,path in re.findall(r'^(ADD|MODIFY|DELETE|RENAME)\t(.+)$',(e/'GIT_DOCUMENT_DIFF_PHASE0V.txt').read_text(),re.M)}
    check(diff==changes,'actual no-index diff mismatch')
    untracked=subprocess.check_output(['git','-C',str(p),'ls-files','--others','--exclude-standard'],text=True).splitlines()
    extra=[k for k in untracked if not k.startswith('docs/keel-integration/')and k not in manifest['python']]
    check(not extra,'new non-document source file')
    broken=[]
    for f in d.rglob('*.md'):
        if 'reference'in f.relative_to(d).parts:continue
        for link in re.findall(r'\]\(([^)]+)\)',f.read_text()):
            target=link.split('#')[0]
            if target and not re.match(r'\w+:|^/',target)and not(f.parent/target).exists():broken.append(str(f.relative_to(d))+': '+link)
    check(not broken,'broken relative links')
    caps=list(csv.DictReader((d/'CAPABILITY_TRACEABILITY.csv').open()))
    check(len(caps)==129 and len({x['capability_id']for x in caps})==129,'capability IDs changed')
    acceptance=list(csv.DictReader((d/'evidence/ACCEPTANCE_TEST_SPEC.csv').open()))
    proposed={'AT-AUTH-'+str(i).zfill(3)for i in range(1,14)}|{'AT-PLATFORM-001'}
    check(proposed<={x['test_id']for x in acceptance},'Phase 1A acceptance references missing')
    dyn=list(csv.DictReader((e/'DYNAMIC_SQL_NATIVE_STATUS.csv').open()))
    check(len(dyn)==23 and all(x['native_status'].startswith('BLOCKED')for x in dyn),'dynamic native status overclaimed')
    counts={}
    for name,expected in [('backend',(150,56,0,0,94)),('auth',(2,0,0,2,0)),('workers',(27,24,0,3,0))]:
        suites=list(XML.parse(e/(name+'-offline.xml')).getroot().iter('testsuite'))
        values={key:sum(int(x.attrib.get(key,0))for x in suites)for key in ['tests','failures','errors','skipped']}
        passed=values['tests']-values['failures']-values['errors']-values['skipped']
        observed=(values['tests'],passed,values['failures'],values['errors'],values['skipped'])
        check(observed==expected,'test evidence count mismatch '+name)
        counts[name]={'passed':passed,**values}
    check(pre['native_capability']['database_connections_attempted']is False and pre['native_capability']['isolated_cluster_proven']is False,'native preflight state overclaimed')
    check('BLOCKED' in (d/'PHASE0V_FINAL_REPORT.md').read_text(),'phase verdict changed')
    result={'document_integrity_result':'PASS'if not errors else'FAIL','phase0v_verdict':'BLOCKED','ready_for_phase1a_approval_review':False,'head':head,'source_integrity':integrity,'selected_policies_preserved':13,'source_commit_reviewed_clean':False,'native_postgresql_verification':'NOT RUN','provider_certification':'NOT RUN','browser_e2e':'NOT RUN','backend_test_counts':counts,'frontend_tests':{'passed':90,'failed':0,'skipped':0},'frontend_build_exit_code':json.loads((e/'frontend-build-command.json').read_text())['exit_code'],'current_document_files':len(current),'incremental_operations':dict(collections.Counter(changes.values())),'ledger_matches':rows==changes,'actual_git_document_inventory_matches':actual==set(current),'git_no_index_diff_matches':diff==changes,'new_non_document_files':extra,'broken_relative_links':broken,'errors':errors,'note':'PASS refers only to document/provenance consistency; five collection errors, 94 DB-dependent skips and all native gates remain blocked. No production implementation authorized.'}
    if a.write_result:(e/'PHASE0V_DOCUMENT_VERIFICATION.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    return 1 if errors else 0

if __name__=='__main__':raise SystemExit(main())
