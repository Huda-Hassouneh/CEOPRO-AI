"""Production template workflow; isolated identity injection, real RLS database."""
from pathlib import Path
import os
import shutil
import subprocess
import threading
import time
import urllib.request

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from src.ai.core.security import TenantContext, get_tenant_context
from src.ai.routers import platform, billing
from .test_custom_self_service_browser import port
from .test_reconciliation_roles import restricted_runtime  # noqa: F401


@pytest.mark.parametrize('locale,width',[('en',1440),('en',390),('ar',1440),('ar',390)])
def test_template_browser(locale,width,platform_owner_context,restricted_runtime):
    root=Path(__file__).resolve().parents[3]
    chrome=next((p for p in [Path(os.environ.get('CHROMIUM_PATH','missing-chrome')),
        Path('C:/Program Files/Google/Chrome/Application/chrome.exe')] if p.is_file()),None)
    assert chrome,'Chrome required for local browser acceptance'
    api_port,ui_port=port(),port()
    api,ui=f'http://127.0.0.1:{api_port}',f'http://127.0.0.1:{ui_port}'
    app=FastAPI()
    app.add_middleware(CORSMiddleware,allow_origins=[ui],allow_methods=['*'],allow_headers=['*'])
    app.include_router(platform.router);app.include_router(billing.router)
    app.dependency_overrides[get_tenant_context]=lambda:TenantContext(*platform_owner_context)
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=api_port,log_level='error'))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    evidence=root/'.dev/evidence/canonical-plan-catalog';evidence.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,VITE_API_BASE_URL=api,APP_URL=ui,API_URL=api,CHROMIUM_PATH=str(chrome),E2E_LOCALE=locale,
             E2E_WIDTH=str(width),SCREENSHOT_PATH=str(evidence/f'template-{locale}-{width}.png'))
    process=subprocess.Popen([shutil.which('node'),'node_modules/vite/bin/vite.js','--host','127.0.0.1','--port',str(ui_port),'--strictPort'],
        cwd=root/'frontend',env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            try:
                with urllib.request.urlopen(ui+'/tests/browser/standard-plan-creation.html',timeout=1):
                    if server.started:break
            except OSError:time.sleep(.1)
        result=subprocess.run([shutil.which('node'),'tests/browser/standard-plan-template.mjs'],cwd=root/'frontend',env=env,
            capture_output=True,text=True,timeout=70)
        assert result.returncode==0,result.stdout+result.stderr
    finally:
        process.terminate();process.wait(timeout=10)
        server.should_exit=True;thread.join(timeout=10)
