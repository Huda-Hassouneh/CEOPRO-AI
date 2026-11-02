// Real Chrome/component interactions with explicitly mocked onboarding HTTP
// persistence. Native PostgreSQL persistence is tested separately by pytest.
import assert from 'node:assert/strict';
import { createServer } from 'vite';
import { chromium } from 'playwright-core';
import { readFileSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const html='<!doctype html><html><head></head><body><div id="root"></div><script type="module" src="/tests/fixtures/onboarding-region.jsx"></script></body></html>';
const server=await createServer({logLevel:'error',plugins:[{name:'region-fixture',configureServer(vite){
  vite.middlewares.use(async(req,res,next)=>{
    if(req.url!=='/region-fixture')return next();
    res.setHeader('Content-Type','text/html');res.end(await vite.transformIndexHtml(req.url,html));
  });
}}],server:{host:'127.0.0.1',port:0}});
await server.listen();
const base=`http://127.0.0.1:${server.httpServer.address().port}`;
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
let checks=0;
try{
  for(const locale of ['en','ar']){
    const context=await browser.newContext({viewport:{width:locale==='ar'?390:1360,height:1000}});
    await context.addInitScript(value=>localStorage.setItem('ceopro_locale',value),locale);
    const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
    let state={revision:0,highestCompletedStep:0,currentStep:1,country:'',city:'',isComplete:false};
    await page.route('**/onboarding/state',async route=>{
      if(route.request().method()==='PUT'){
        const payload=route.request().postDataJSON();assert.equal(payload.country.length,2);assert.equal(payload.language,locale);
        state={...state,...payload,revision:state.revision+1,highestCompletedStep:1,currentStep:2};
      }
      await route.fulfill({json:state});
    });
    const labels=JSON.parse(readFileSync(`src/assets/locales/${locale}.json`,'utf8'));
    await page.goto(base+'/region-fixture');await page.locator('#setup-country').waitFor();
    assert.equal(await page.locator('#setup-country').inputValue(),'');
    assert.equal(await page.locator('#setup-country option').count(),250);
    const next=page.getByRole('button',{name:labels.onboarding.common.continue,exact:true});
    assert.equal(await next.isDisabled(),true);
    for(const [country,search,city] of [['JO','Amman','amman'],['US','New York','new-york-city'],['DE','Berlin','berlin'],['JP','Tokyo','tokyo'],['BR','São Paulo','sao-paulo'],['ZA','Johannesburg','johannesburg'],['AU','Sydney','sydney']]){
      await page.locator('#setup-country').selectOption(country);
      await page.locator('#setup-city-search').waitFor({state:'visible'});
      await page.waitForFunction(()=>!document.querySelector('#setup-city-search').disabled);
      assert.equal(await page.locator('#setup-city').inputValue(),'');
      await page.locator('#setup-city-search').fill(search);
      await page.locator(`#setup-city option[value="${city}"]`).waitFor({state:'attached'});
      await page.locator('#setup-city').selectOption(city);assert.equal(await next.isEnabled(),true);
      await next.click();await page.getByRole('heading',{name:'Industry fixture'}).waitFor();
      await page.getByRole('link',{name:'Back to region'}).click();
      assert.equal(await page.locator('#setup-country').inputValue(),country);
      assert.equal(await page.locator('#setup-city').inputValue(),city);
      await page.reload();await page.locator('#setup-city').waitFor();
      await page.waitForFunction(value=>document.querySelector('#setup-city')?.value===value,city);
      checks++;
    }
    await page.locator('#setup-country').selectOption('JO');await page.waitForFunction(()=>!document.querySelector('#setup-city-search').disabled);
    await page.locator('#setup-city-search').fill(locale==='ar'?'عمّان':'Amman');
    await page.locator('#setup-city').selectOption('amman');
    await page.locator('#setup-country').selectOption('DE');await page.waitForFunction(()=>!document.querySelector('#setup-city-search').disabled);
    assert.equal(await page.locator('#setup-city').inputValue(),'');assert.equal(await next.isDisabled(),true);
    await page.locator('#setup-city-search').fill('Amman');assert.equal(await page.locator('#setup-city option[value="amman"]').count(),0);
    assert.equal(await page.locator('html').getAttribute('dir'),locale==='ar'?'rtl':'ltr');
    await page.locator('#setup-city-search').fill('Berlin');await page.locator('#setup-city').selectOption('berlin');
    const out=resolve('../.dev/evidence/onboarding-region');mkdirSync(out,{recursive:true});await page.screenshot({path:resolve(out,`${locale}.png`),fullPage:true});
    assert.deepEqual(errors,[]);checks++;await context.close();
  }
  console.log(`PASS: ${checks} Chrome region scenarios (EN desktop / AR mobile); mocked HTTP persistence, real country assets and UI.`);
}finally{await browser.close();await server.close();}
