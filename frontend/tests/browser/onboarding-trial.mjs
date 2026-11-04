// Actual Chrome + production React components. No customer/provider/DB writes.
// Native SQL/endpoint behavior is covered independently by backend tests.
import assert from 'node:assert/strict';
import { createServer } from 'vite';
import { chromium } from 'playwright-core';
import { readFileSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

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
const screenshotDir=process.env.ONBOARDING_SCREENSHOT_DIR;
if(screenshotDir)mkdirSync(screenshotDir,{recursive:true});
const plans=[['starter','Standard',14],['growth','Plus',14],['enterprise','Pro',7],['no-trial','No trial',0]].map(([plan_key,name,trial_days],tier_level)=>({
  plan_key,name:{en:name,ar:name},trial_days,tier_level,self_serve:true,monthly_price:29+tier_level*30,currency:'USD',limits:{tracked_products:100},
  prices:[{period_code:'monthly',interval_months:1,amount:29+tier_level*30,currency:'USD',discount_percent:0,purchasable:true}],
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
        await page.locator('.ceopro-plan-card').first().waitFor().catch(error=>{
          throw new Error(JSON.stringify({locale,scenario,errors,body:page.url()}),{cause:error});
        });
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
          const primary=page.locator('.ceopro-payment-method > .ceopro-button--primary');
          assert.equal(await primary.count(),1);
          assert.equal(await page.getByRole('button',{name:labels.billing.onboarding.continueStripe,exact:true}).count(),0);
          assert.equal(await primary.innerText(),plan.trial_days?labels.billing.onboarding.startTrial.replace('{{days}}',plan.trial_days):labels.billing.payment.continueSecureCheckout);
          const selectedCard=page.getByRole('complementary',{name:labels.billing.payment.selectedPlan});
          await selectedCard.getByRole('heading',{name:plan.name.en,exact:true}).waitFor();
          assert.ok((await page.locator('.ceopro-plan-summary__headline-price').innerText()).includes(new Intl.NumberFormat(locale==='ar'?'ar-JO':'en-US',{style:'currency',currency:plan.currency}).format(plan.prices[0].amount)));
          const visual=await selectedCard.evaluate(card=>({border:parseFloat(getComputedStyle(card).borderTopWidth),nameSize:parseFloat(getComputedStyle(card.querySelector('h2')).fontSize),priceSize:parseFloat(getComputedStyle(card.querySelector('.ceopro-plan-summary__headline-price strong')).fontSize)}));
          assert.ok(visual.border>=2&&visual.nameSize>=26&&visual.priceSize>=28);
          assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true);
          assert.equal(await page.locator('.ceopro-payment-security button').count(),0);
          if(screenshotDir&&scenario==='growth')await page.screenshot({path:resolve(screenshotDir,`plus-payment-${locale}.png`),fullPage:true});
          await selectedCard.locator('summary').click();
          assert.equal(await selectedCard.locator('.ceopro-plan-summary__feature').first().isVisible(),true);
          assert.equal(activations.length,0); // Selection/review alone must not issue a trial.
          assert.equal(state.selectedPlan,scenario);
          if(plan.trial_days){
            await primary.click();
            await page.getByRole('heading',{name:'Provider checkout fixture'}).waitFor();
            assert.deepEqual(activations,[{plan_key:scenario,period_code:'monthly'}]);assert.equal(checkouts.length,0);
            assert.deepEqual(subscription,original); // A redirect grants no local rights.
            await page.goto(base+'/trial-fixture');
            await page.locator('.ceopro-plan-card').first().waitFor();
            assert.equal(await page.getByRole('button',{name:labels.onboarding.persistence.currentTrial,exact:true}).count(),0);
          }else{
            assert.equal(await page.locator('.ceopro-plan-summary__trial-badge').count(),0);
            await primary.click();
            await page.getByRole('alert').waitFor();
            assert.equal(activations.length,0);assert.equal(checkouts[0].plan_key,scenario);
          }
        }
      }
      assert.equal(await page.locator('html').getAttribute('dir'),locale==='ar'?'rtl':'ltr');
      assert.deepEqual(errors,[]);checks++;await context.close();
    }
  }
  for(const locale of ['en','ar']){
    const labels=JSON.parse(readFileSync(`src/assets/locales/${locale}.json`,'utf8'));
    for(const scenario of ['resume-trial','resume-existing','conflict','unknown-error','busy','promo']){
      const context=await browser.newContext({viewport:{width:locale==='ar'?390:1360,height:1000}});
      await context.addInitScript(value=>localStorage.setItem('ceopro_locale',value),locale);
      const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
      let conflict=scenario==='conflict',closed=0,requests=0;
      const existing=scenario==='resume-existing';
      const issued={assigned:existing,hasAccess:existing,status:existing?'trialing':'none',planId:existing?'growth':null,trialUsed:existing,trialAvailable:!existing,trialEligiblePlanIds:existing?[]:['growth'],hasSubscription:false,...(existing?{checkoutTrialEndsAt:1794814640,trialEndsAt:'2026-11-16T07:37:20Z'}:{})};
      let releaseCheckout;
      const waitCheckout=new Promise(resolve=>{releaseCheckout=resolve;});
      let state={revision:4,highestCompletedStep:5,currentStep:6,isComplete:false,selectedPlan:'growth',billingPeriod:'monthly'};
      await page.route('https://checkout.stripe.test/**',r=>r.fulfill({contentType:'text/html',body:'<h1>Resumed checkout fixture</h1>'}));
      await page.route(url=>url.pathname.startsWith('/api/'),async route=>{
        const path=new URL(route.request().url()).pathname.replace('/api','');
        if(path==='/billing/plans')return route.fulfill({json:{plans,payments_enabled:true}});
        if(path==='/billing/subscription')return route.fulfill({json:issued});
        if(path==='/onboarding/state'){
          if(route.request().method()==='PUT')state={...state,...route.request().postDataJSON(),revision:state.revision+1};
          return route.fulfill({json:state});
        }
        if(path==='/billing/checkout/cancel-pending'){closed++;conflict=false;return route.fulfill({json:{state:'checkout_cancelled'}});}
        if(path==='/billing/promotions/validate'){
          assert.equal(scenario,'promo');
          assert.deepEqual(route.request().postDataJSON(),{code:'WELCOME',plan_key:'growth',period_code:'monthly'});
          return route.fulfill({json:{valid:true,promotion:{discount_type:'percent',discount_value:10}}});
        }
        if(path==='/billing/trial'||path==='/billing/checkout'){
          assert.equal(path,existing?'/billing/checkout':'/billing/trial');
          if(scenario==='promo')assert.equal(route.request().postDataJSON().promotion_code,'WELCOME');
          requests++;
          if(scenario==='busy')await waitCheckout;
          if(conflict||scenario==='unknown-error')return route.fulfill({status:409,json:{detail:{reason:conflict?'checkout_pending':'future_provider_reason'}}});
          return route.fulfill({json:{url:'https://checkout.stripe.test/existing-session',session_id:'cs_existing_fixture'}});
        }
        throw new Error('Unexpected recovery HTTP: '+path);
      });
      const payment=base+'/trial-fixture?entry='+encodeURIComponent('/onboarding/plan/payment?plan=growth&period=monthly');
      await page.goto(payment);await page.locator('.ceopro-payment-method').waitFor();
      const selector='.ceopro-payment-method > .ceopro-button--primary';
      assert.equal(await page.locator(selector).count(),1);
      assert.equal(await page.locator(selector).innerText(),existing?labels.billing.payment.continueSecureCheckout:labels.billing.onboarding.startTrial.replace('{{days}}',14));
      if(existing){
        assert.equal(await page.locator('.ceopro-plan-summary__trial-badge').count(),0);
        await page.locator('time[datetime="2026-11-16T07:37:20.000Z"]').waitFor();
      }
      if(scenario==='promo'){
        await page.getByRole('textbox').fill('welcome');
        await page.getByRole('button',{name:labels.billing.coupon.apply,exact:true}).click();
        await page.locator('.billing-coupon-success').waitFor();
      }
      await page.locator(selector).click();
      if(scenario==='busy'){
        await page.waitForFunction(()=>document.querySelector('.ceopro-payment-method > .ceopro-button--primary')?.disabled);
        assert.equal(await page.locator(selector).getAttribute('aria-busy'),'true');
        assert.equal(await page.getByRole('textbox').isDisabled(),true);
        await page.locator(selector).evaluate(button=>button.click());
        assert.equal(requests,1);releaseCheckout();
      }
      if(scenario==='conflict'||scenario==='unknown-error'){
        const alert=page.getByRole('alert');await alert.waitFor();
        assert.equal(await alert.innerText(),labels.billing.errors[scenario==='conflict'?'checkout_pending':'generic']);
        assert.ok(!(await page.locator('body').innerText()).includes('billing.errors.'));
        if(scenario==='conflict'){
          await page.getByRole('button',{name:labels.billing.returnState.closeCheckout,exact:true}).click();
          await page.getByRole('alert').filter({hasText:labels.billing.returnState.closed}).waitFor();
          assert.equal(closed,1);
          await page.locator(selector).click();await page.getByRole('heading',{name:'Resumed checkout fixture'}).waitFor();
        }
      }else if(scenario==='busy'||scenario==='promo'){
        await page.getByRole('heading',{name:'Resumed checkout fixture'}).waitFor();assert.equal(requests,1);
      }else{
        await page.getByRole('heading',{name:'Resumed checkout fixture'}).waitFor();
        // Return without completing, then reload the Payment Method page.
        await page.goBack();await page.locator('.ceopro-payment-method').waitFor();
        await page.reload();await page.locator('.ceopro-payment-method').waitFor();
        await page.locator(selector).click();await page.getByRole('heading',{name:'Resumed checkout fixture'}).waitFor();
        assert.equal(page.url(),'https://checkout.stripe.test/existing-session');assert.equal(requests,2);
      }
      assert.equal(issued.hasAccess,existing);assert.equal(issued.trialUsed,existing);
      assert.deepEqual(errors,[]);checks++;await context.close();
    }
  }
  console.log(`PASS: ${checks} Chrome trial/onboarding/recovery scenarios (EN desktop, AR mobile); HTTP/provider boundaries doubled.`);
}finally{await browser.close();await server.close();}
