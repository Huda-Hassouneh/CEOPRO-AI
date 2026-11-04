// Actual Chrome + production React components. No customer/provider/DB writes.
// Native SQL/endpoint behavior is covered independently by backend tests.
import assert from 'node:assert/strict';
import { createServer } from 'vite';
import { chromium } from 'playwright-core';
import { readFileSync } from 'node:fs';

const html='<!doctype html><html><head></head><body><div id="root"></div><script type="module" src="/tests/fixtures/onboarding-trial.jsx"></script></body></html>';
const server=await createServer({envDir:false,define:{'import.meta.env.VITE_API_BASE_URL':JSON.stringify('/api')},logLevel:'error',plugins:[{name:'trial-fixture',configureServer(vite){
  vite.middlewares.use(async(req,res,next)=>{
    if(!req.url.startsWith('/trial-fixture'))return next();
    res.setHeader('Content-Type','text/html');res.end(await vite.transformIndexHtml(req.url,html));
  });
}}],server:{host:'127.0.0.1',port:0}});
await server.listen();
const base=`http://127.0.0.1:${server.httpServer.address().port}`;
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const plans=[['starter','Standard',14],['growth','Plus',14],['enterprise','Pro',7],['no-trial','No trial',0]].map(([plan_key,name,trial_days],tier_level)=>({
  plan_key,name:{en:name,ar:name},trial_days,tier_level,self_serve:true,monthly_price:29,currency:'USD',limits:{tracked_products:100},
  prices:[{period_code:'monthly',interval_months:1,amount:29,currency:'USD',discount_percent:0,purchasable:true}],
}));
let checks=0;
try{
  for(const locale of ['en','ar']){
    const labels=JSON.parse(readFileSync(`src/assets/locales/${locale}.json`,'utf8'));
    for(const scenario of ['starter','growth','enterprise','no-trial','existing','dashboard-incomplete','dashboard-no-access','dashboard-valid']){
      const context=await browser.newContext({viewport:{width:locale==='ar'?390:1360,height:1000}});
      await context.addInitScript(value=>localStorage.setItem('ceopro_locale',value),locale);
      const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
      const existing=scenario==='existing',dashboard=scenario.startsWith('dashboard');
      let state={revision:4,highestCompletedStep:4,currentStep:5,isComplete:false,selectedPlan:'',billingPeriod:'monthly'};
      let subscription={assigned:false,hasAccess:false,status:'none',planId:null,trialUsed:false,trialAvailable:true,trialEligiblePlanIds:['starter','growth','enterprise'],hasSubscription:false,billingPeriod:'monthly'};
      if(existing||scenario==='dashboard-valid')subscription={...subscription,assigned:true,hasAccess:true,status:'trialing',source:'trial',planId:'growth',trialUsed:true,trialAvailable:false,trialEligiblePlanIds:[],trialEndsAt:'2026-11-16T07:37:20Z',checkoutTrialEndsAt:1794814640};
      const original=structuredClone(subscription),activations=[],checkouts=[];
      await page.route('https://checkout.stripe.test/**',route=>route.fulfill({contentType:'text/html',body:`<!doctype html><html dir="${locale==='ar'?'rtl':'ltr'}"><body><h1>Provider checkout fixture</h1></body></html>`}));
      await page.route(url=>url.pathname.startsWith('/api/'),async route=>{
        const path=new URL(route.request().url()).pathname.replace('/api',''),body=route.request().postDataJSON();
        if(path==='/billing/plans')return route.fulfill({json:{plans,payments_enabled:true}});
        if(path==='/billing/subscription')return route.fulfill({json:subscription});
        if(path==='/onboarding/state'){
          if(route.request().method()==='PUT'){
            assert.equal(body.step,5);assert.equal(body.expected_revision,state.revision);
            state={...state,...body,revision:state.revision+1,highestCompletedStep:5,currentStep:6};
          }
          return route.fulfill({json:state});
        }
        if(path==='/settings/company')return route.fulfill({json:{onboarding_completed_at:scenario==='dashboard-incomplete'?null:'2026-11-02T08:00:00Z'}});
        if(path==='/billing/trial'){
          assert.equal(state.selectedPlan,body.plan_key);activations.push(body);
          return route.fulfill({json:{url:'https://checkout.stripe.test/pending-trial',session_id:'cs_fixture'}});
        }
        if(path==='/billing/checkout'){checkouts.push(body);return route.fulfill({status:503,json:{detail:{reason:'provider_unavailable'}}});}
        throw new Error('Unexpected fixture HTTP: '+path);
      });
      await page.goto(base+'/trial-fixture'+(dashboard?'?entry=/dashboard':''));
      if(dashboard){
        if(scenario==='dashboard-incomplete')await page.getByRole('heading',{name:'Onboarding required',exact:true}).waitFor();
        else if(scenario==='dashboard-valid')await page.getByRole('heading',{name:'Dashboard fixture',exact:true}).waitFor();
        else await page.locator('.ceopro-plan-card').first().waitFor();
        assert.equal(activations.length,0);
      }else{
        await page.locator('.ceopro-plan-card').first().waitFor();
        const current=page.getByRole('button',{name:labels.onboarding.persistence.currentTrial,exact:true});
        if(existing){
          await current.click();await page.getByRole('heading',{name:'Connections fixture'}).waitFor();
          assert.equal(state.selectedPlan,'growth');assert.equal(activations.length,0);assert.deepEqual(subscription,original);
        }else{
          assert.equal(await current.count(),0);assert.equal(await page.locator('.ceopro-plan-card.is-selected').count(),0);
          const plan=plans.find(p=>p.plan_key===scenario);
          const card=page.getByRole('article',{name:plan.name.en,exact:true});
          if(plan.trial_days)assert.ok((await card.innerText()).includes(String(plan.trial_days)));
          await card.getByRole('button').click();
          await page.getByRole('button',{name:labels.onboarding.common.continue,exact:true}).click();
          await page.locator('.ceopro-payment-method').waitFor();
          assert.equal(activations.length,0); // Selection/review alone must not issue a trial.
          assert.equal(state.selectedPlan,scenario);
          if(plan.trial_days){
            await page.locator('.billing-payment-boundary button').click();
            await page.getByRole('heading',{name:'Provider checkout fixture'}).waitFor();
            assert.deepEqual(activations,[{plan_key:scenario,period_code:'monthly'}]);assert.equal(checkouts.length,0);
            assert.deepEqual(subscription,original); // A redirect grants no local rights.
            await page.goto(base+'/trial-fixture');
            await page.locator('.ceopro-plan-card').first().waitFor();
            assert.equal(await page.getByRole('button',{name:labels.onboarding.persistence.currentTrial,exact:true}).count(),0);
          }else{
            assert.equal(await page.locator('.billing-payment-boundary').count(),0);
            await page.locator('.ceopro-payment-method button').click();
            await page.getByRole('alert').waitFor();
            assert.equal(activations.length,0);assert.equal(checkouts[0].plan_key,scenario);
          }
        }
      }
      assert.equal(await page.locator('html').getAttribute('dir'),locale==='ar'?'rtl':'ltr');
      assert.deepEqual(errors,[]);checks++;await context.close();
    }
  }
  console.log(`PASS: ${checks} Chrome trial/onboarding scenarios (EN desktop, AR mobile); HTTP/provider boundaries doubled.`);
}finally{await browser.close();await server.close();}
