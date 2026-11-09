"""Real owner Billing UI -> production API -> restricted disposable PostgreSQL.

Identity injection is explicit; no login or external payment is simulated as real.
"""
from contextlib import closing
from pathlib import Path
import os
import shutil
import subprocess
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from src.ai import db
from src.ai.billing import plan_studio
from src.ai.routers import platform, billing
from src.ai.core.security import TenantContext, get_tenant_context
from .test_custom_self_service_browser import port, browser_executable
from .test_reconciliation_roles import restricted_runtime  # noqa: F401
from .test_plan_studio import policy_body


@pytest.mark.parametrize('role,locale,scenario',[('owner','en','complete'),('owner','ar','complete'),('tenant','en','denied'),('owner','en','missing'),('owner','en','legacy'),('owner','ar','legacy')])
def test_browser_pricing_studio(role,locale,scenario,platform_owner_context,tenant,restricted_runtime):
    root=Path(__file__).resolve().parents[3]
    chrome=browser_executable()
    with closing(db.app_role_connection(*platform_owner_context)) as conn:
        sources=plan_studio.bootstrap(conn)
        body=policy_body(sources)
        if scenario=='missing':
            # Explicit separate external cost with no binding remains missing;
            # known local feature coverage no longer needs manual discovery.
            body['assumptions']['feature_treatments']['monthly_reports']='additional_external'
        if scenario=='legacy':
            from .test_plan_internal_costs import legacy
            body['assumptions']=legacy(body['assumptions'])
            plan_studio.command(conn,'create_policy',body)
        else:
            plan_studio.create_policy(conn,plan_studio.PolicyCreate.model_validate(body))
        conn.commit()
    api_port,ui_port=port(),port()
    api,ui=f'http://127.0.0.1:{api_port}',f'http://127.0.0.1:{ui_port}'
    app=FastAPI()
    app.add_middleware(CORSMiddleware,allow_origins=[ui],allow_methods=['*'],allow_headers=['*'])
    app.include_router(platform.router)
    # Feature grouping uses the read-only customer configurator catalog.
    app.include_router(billing.router)
    app.dependency_overrides[get_tenant_context]=lambda:TenantContext(*(platform_owner_context if role=='owner' else tenant))
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=api_port,log_level='error'))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    evidence=root/'.dev/evidence/standard-pricing-studio'
    evidence.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,VITE_API_BASE_URL=api,APP_URL=ui,API_URL=api,CHROMIUM_PATH=str(chrome),E2E_LOCALE=locale,STUDIO_ROLE=role,STUDIO_SCENARIO=scenario,
        SCREENSHOT_PATH=str(evidence/f'{role}-{locale}-{scenario}.png'))
    process=subprocess.Popen([shutil.which('node'),'node_modules/vite/bin/vite.js','--host','127.0.0.1','--port',str(ui_port),'--strictPort'],
        cwd=root/'frontend',env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        import urllib.request
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            try:
                with urllib.request.urlopen(ui+'/tests/browser/pricing-studio.html',timeout=1):
                    if server.started:break
            except OSError:time.sleep(.1)
        result=subprocess.run([shutil.which('node'),'tests/browser/pricing-studio.mjs'],cwd=root/'frontend',env=env,
            capture_output=True,text=True,timeout=70)
        assert result.returncode==0,result.stdout+result.stderr
    finally:
        process.terminate();process.wait(timeout=10)
        server.should_exit=True;thread.join(timeout=10)
