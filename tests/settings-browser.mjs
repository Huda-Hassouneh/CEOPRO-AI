import { chromium } from '../../tmp/visual-qa/node_modules/playwright-core/index.mjs';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
fs.mkdirSync('tmp/settings-screens',{recursive:true});
const failures=[];
for(const role of ['ADMIN','EDITOR','VIEWER']) {
 const context=await browser.newContext({viewport:{width:1440,height:950}});
 await context.addInitScript(({role})=>localStorage.setItem('ceopro_auth_session',JSON.stringify({user:{id:'settings-test',full_name:'Settings Test',email:'settings@example.test',company:{business_name:'Example Workspace',country_code:'JO',primary_currency:'JOD',business_type:'Retail'}},roles:[role],tenantId:'settings-test-workspace',accessToken:'local-ui-fixture'})),{role});
 const page=await context.newPage();page.on('pageerror',e=>failures.push(e.message));
 await page.goto('http://127.0.0.1:5181/settings');
 await page.getByRole('textbox',{name:'Full Name',exact:true}).waitFor();
 assert.equal(await page.getByRole('textbox',{name:'Full Name',exact:true}).inputValue(),'Settings Test');
 assert.equal(await page.getByRole('button',{name:'Save Changes'}).isDisabled(),true);
 await page.getByRole('tab',{name:'Company',exact:true}).click();await page.getByText('Example Workspace',{exact:true}).waitFor();
 await page.getByRole('tab',{name:'Team Members',exact:true}).click();
 await page.getByText('team totals cannot be determined.',{exact:false}).waitFor();
 assert.equal(await page.locator('.settings-team-summary').count(),0);
 assert.equal(await page.getByRole('button',{name:'Invite Member',exact:true}).count(),role==='ADMIN'?1:0);
 if(role==='ADMIN'){
  await page.getByRole('button',{name:'Invite Member',exact:true}).click();
  assert.equal(await page.getByRole('button',{name:'Send Invitation',exact:true}).isDisabled(),true);
  await page.getByRole('button',{name:'Cancel',exact:true}).focus();await page.keyboard.press('Tab');
  assert.equal(await page.evaluate(()=>document.activeElement.closest('[role="dialog"]')!==null),true);
  await page.keyboard.press('Escape');assert.equal(await page.getByRole('dialog').count(),0);
  await page.screenshot({path:'tmp/settings-screens/team-en.png',fullPage:true});
 }
 await page.getByRole('tab',{name:'Security',exact:true}).click();assert.equal(await page.getByRole('button',{name:'Change Password',exact:true}).isDisabled(),true);
 assert.equal(await page.locator('input[type="password"]:disabled').count(),3);
 await page.getByRole('tab',{name:'Preferences',exact:true}).click();await page.locator('input[value="ar"]').check();
 await page.waitForFunction(()=>document.documentElement.dir==='rtl');
 await page.setViewportSize({width:390,height:844});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth),true);
 await page.waitForTimeout(220);
 assert.equal(await page.locator('.business-sidebar').evaluate(el=>el.getBoundingClientRect().left>=window.innerWidth),true);
 if(role==='ADMIN')await page.screenshot({path:'tmp/settings-screens/preferences-ar-mobile.png',fullPage:true});
 const tab=page.getByRole('tab').nth(4);await tab.focus();await page.keyboard.press('ArrowLeft');assert.match(page.url(),/tab=security/);
 await page.reload();assert.equal(await page.evaluate(()=>document.documentElement.dir),'rtl');
 await context.close();
}
assert.deepEqual(failures,[]);await browser.close();console.log('PASS: all 3 roles, disabled unsupported actions, real schema mapping, honest directory, modal keyboard behavior, RTL tabs, mobile overflow, locale persistence, no page errors.');
