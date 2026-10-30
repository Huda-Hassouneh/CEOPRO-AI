"""Verify the meeting's read-only UI actions without additional AI calls."""
import json
import os
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit

import dev
from seed_meeting_demo import ACCOUNT, read


def main():
    from playwright.sync_api import sync_playwright
    c=dev.config()
    a=read(ACCOUNT)
    e=dev.STATE/'evidence/meeting-phase2'
    origin=f"http://127.0.0.1:{c['ports']['frontend']}"
    chrome=next(str(Path(base)/'Google/Chrome/Application/chrome.exe') for base in (os.environ.get('ProgramFiles'),os.environ.get('ProgramFiles(x86)'),os.environ.get('LOCALAPPDATA')) if base and (Path(base)/'Google/Chrome/Application/chrome.exe').exists())
    checks=[]
    started=monotonic()
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=chrome,headless=True)
        ctx=browser.new_context(viewport={'width':1440,'height':1000})
        ctx.add_init_script("localStorage.setItem('ceopro_locale','en')")
        p=ctx.new_page()
        def check(name,ok):
            checks.append({'name':name,'status':'PASS' if ok else 'FAIL','elapsed_seconds':round(monotonic()-started,1)})
            print(checks[-1]['status']+': '+name,flush=True)
            dev.write_json(e/'rehearsal.json',checks)
        def visit(route):
            p.goto(origin+route)
            p.wait_for_load_state('networkidle')
        p.goto(origin+'/login')
        p.locator('input[type="email"]').fill(a['email'])
        p.locator('input[type="password"]').fill(a['password'])
        p.locator('button[type="submit"]').click()
        p.wait_for_url(lambda u:urlsplit(u).path!='/login',timeout=30000)
        check('designated tenant login',p.evaluate("JSON.parse(localStorage.getItem('ceopro_auth_session')).tenantId")==a['tenant_id'])
        visit('/dashboard')
        for days,expected in [(7,'3,448'),(90,'47,600'),(30,'16,203')]:
            p.get_by_role('button',name=f'{days} days',exact=True).click()
            p.wait_for_load_state('networkidle')
            p.wait_for_timeout(500)
            check(f'{days}-day dashboard revenue visible',expected in p.locator('body').inner_text())
        catalog=read(e/'forecast.json')['products']
        pid=next(x['product_id'] for x in catalog if x['name']=='Extra Virgin Olive Oil 1L')
        visit('/products/'+pid)
        text=p.locator('body').inner_text()
        check('product detail contains original stock and price','140' in text and '9.5' in text)
        p.screenshot(path=str(e/'rehearsal-product.png'),full_page=True)
        visit('/demand')
        check('real forecast and restock UI', '1,817' in p.locator('body').inner_text())
        visit('/pricing')
        row=p.get_by_role('row').filter(has_text='Extra Virgin Olive Oil 1L')
        row.get_by_role('button',name='Recommendation history',exact=True).click()
        p.locator('.pricing-history').wait_for()
        check('persisted pricing decision history opens','hold' in p.locator('.pricing-history').inner_text().lower())
        p.screenshot(path=str(e/'rehearsal-pricing-history.png'),full_page=True)
        visit('/reports')
        check('report table shows seeded invoices','DEMO-20261027' in p.locator('body').inner_text())
        visit('/connect-data')
        check('completed import filename visible','synthetic-sales' in p.locator('body').inner_text())
        visit('/marketing')
        p.locator('.studio-history__open').first.click()
        p.wait_for_load_state('networkidle')
        p.wait_for_timeout(700)
        check('persisted campaign and generated image open',p.locator('img').evaluate_all('(images)=>images.some(i=>i.complete && i.naturalWidth>=768)'))
        p.screenshot(path=str(e/'rehearsal-marketing.png'),full_page=True)
        visit('/billing')
        text=p.locator('body').inner_text()
        check('trial and AI usage displayed','TRIAL' in text and '0.2 / 111' in text)
        # Reopen the previously accepted document-grounded conversation, no send.
        q=read(dev.STATE/'evidence/rag-503/real-question-1.private.json')
        p.evaluate('([key,value])=>localStorage.setItem(key,value)',['ceopro.rag-assistant.session-id.'+a['tenant_id'],q['session_id']])
        visit('/ai-advisor')
        p.locator('.rag-message').last.wait_for()
        p.locator('.rag-sources__toggle').last.click()
        p.locator('.rag-sources__list button').last.click()
        p.locator('.rag-reference-panel').wait_for()
        check('document citation panel opens from persisted history',bool(p.locator('.rag-reference-panel').inner_text().strip()))
        p.screenshot(path=str(e/'rehearsal-citation.png'),full_page=True)
        browser.close()
    dev.write_json(e/'rehearsal-summary.json',{'checks':len(checks),'elapsed_seconds':round(monotonic()-started,1),'status':'PASS' if all(x['status']=='PASS' for x in checks) else 'FAIL','new_generation_requests':0})


if __name__=='__main__':
    main()
