from pathlib import Path
import subprocess,os,sys,json,time,importlib.metadata,platform
ROOT=Path('/workspace/scratch/327eb0b847b6');P=ROOT/'repos/main-repo/main-repo/CEOPRO-AI';E=P/'docs/keel-integration/evidence/phase0v';PY=Path(sys.executable);target=sys.argv[1]
env={k:v for k,v in os.environ.items()if k in ['PATH','LANG','LC_ALL','TMPDIR']};env.update(PYTHONDONTWRITEBYTECODE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',FORECAST_AUTO_REFRESH='0',DISCOVERY_REFRESH_ENABLED='0',NOTIFICATION_DIGEST_ENABLED='0',BILLING_MAINTENANCE_ENABLED='0',KEEL_TEST_DISABLE_METERING='0',UNASSIGNED_PLAN_ACCESS='none',OMP_NUM_THREADS='1')
# Verification-local transport fence; never part of application source.
hooks=ROOT/'analysis/phase0v/network-fence';hooks.mkdir(exist_ok=True)
(hooks/'sitecustomize.py').write_text('''import socket
_connect=socket.socket.connect
_connect_ex=socket.socket.connect_ex
def blocked(self,address):
    if self.family in (socket.AF_INET,socket.AF_INET6):
        raise RuntimeError("PHASE0V_OFFLINE_NETWORK_REFUSED")
    return _connect(self,address)
def blocked_ex(self,address):
    if self.family in (socket.AF_INET,socket.AF_INET6):
        raise RuntimeError("PHASE0V_OFFLINE_NETWORK_REFUSED")
    return _connect_ex(self,address)
socket.socket.connect=blocked
socket.socket.connect_ex=blocked_ex
''')
env['PYTHONPATH']=str(hooks)+os.pathsep+str(ROOT/'analysis/venv/lib/python3.12/site-packages')+os.pathsep+str(P/'backend')
if target=='backend':
 cwd=P/'backend';cmd=[str(PY),'-m','scripts.integration_review','--junitxml',str(E/'backend-offline.xml')]
elif target=='auth':
 cwd=P/'backend';cmd=[str(PY),'-m','pytest','-q','-ra','-p','no:cacheprovider','src/ai/tests/test_auth.py','src/ai/tests/test_auth_completeness.py','--junitxml',str(E/'auth-offline.xml')]
elif target=='workers':
 cwd=P/'backend';cmd=[str(PY),'-m','pytest','-q','-ra','-p','no:cacheprovider','--continue-on-collection-errors',*[f'src/market_scraper/tests/test_{n}.py'for n in ['worker','analysis_worker','discovery_worker','connector_sync','api_connector_sync','network_security']],'--junitxml',str(E/'workers-offline.xml')]
elif target=='frontend-test':cwd=P/'frontend';cmd=['npm','test']
elif target=='frontend-build':cwd=P/'frontend';cmd=['npm','run','build','--','--outDir',str(ROOT/'analysis/phase0v/frontend-dist'),'--emptyOutDir']
else:raise SystemExit('unknown target')
start=time.time()
with(E/(target+'.log')).open('w')as out:
 out.write('COMMAND: '+json.dumps(cmd)+'\nCWD: '+str(cwd)+'\nPROFILE: clean allowlisted environment; no inherited DB/provider secrets; Python TCP fence; metering enabled/unassigned none\n');out.flush()
 result=subprocess.run(cmd,cwd=cwd,env=env,stdout=out,stderr=subprocess.STDOUT)
record={'target':target,'command':cmd,'cwd':str(cwd),'exit_code':result.returncode,'seconds':round(time.time()-start,3),'environment':'allowlist PATH/LANG/LC_ALL/TMPDIR; no DB/Stripe/provider settings inherited; Python socket TCP fence; production metering defaults; offline background/model flags','network':'No live providers or databases authorized; no Docker/server available','log':target+'.log'}
(E/(target+'-command.json')).write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record))
raise SystemExit(result.returncode)
