// Synthetic presentation fixtures only; production pages always use Python APIs.
import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { createServer } from 'vite';
let vite;
test.before(async()=>{vite=await createServer({server:{middlewareMode:true},appType:'custom',logLevel:'silent'});});
test.after(async()=>{await vite.close();});
async function render(locale, file, name, props) {
  const {I18nProvider}=await vite.ssrLoadModule('/src/app/providers/I18nProvider.jsx');
  const component=(await vite.ssrLoadModule('/src/features/billing/components/'+file))[name];
  const original=globalThis.window;
  globalThis.window={localStorage:{getItem:()=>locale}};
  try {
    return renderToStaticMarkup(React.createElement(QueryClientProvider,{client:new QueryClient()},
      React.createElement(MemoryRouter,null,React.createElement(I18nProvider,null,React.createElement(component,props)))));
  } finally { if(original===undefined)delete globalThis.window;else globalThis.window=original; }
}
for(const locale of ['en','ar']) {
  test(`subscription review renders the tenant-scoped backend preview and its payment policy in ${locale}`,async()=>{
    const html=await render(locale,'PlanChangePreview.jsx','PlanChangePreview',{
      subscription:{hasStripeSubscription:true},preview:{data:{timing:'period_end',payment_policy:'next_period_price',feature_changes:[{feature_code:'tracked_products',before:250,after:100,over_limit:true}],effective_at:'2026-11-25T12:00:00Z'}},
    });
    assert.match(html,/250/);assert.match(html,/100/);
    assert.ok(!html.includes('billing.customPlan.featureNames.'));
    assert.ok(!html.includes('$0'));
  });
  test(`original invoice table renders historical amounts and safe documents in ${locale}`,async()=>{
    const {translations,translate}=await vite.ssrLoadModule('/src/shared/lib/i18n.js');
    const t=(key)=>translate(locale,key);
    const html=await render(locale,'InvoiceHistoryTable.jsx','InvoiceHistoryTable',{locale,t,invoices:[
      {id:'in_synthetic',amount:52.75,currency:'USD',date:'2026-10-25',type:'subscription',paymentStatus:'failed',pdfUrl:'https://pay.stripe.com/synthetic.pdf'},
      {id:'in_unsafe',amount:10,currency:'USD',date:'2026-10-24',type:'subscription',paymentStatus:'paid',pdfUrl:'javascript:alert(1)'},
    ]});
    assert.match(html,/billing-invoice-table/);
    assert.ok(html.includes(translations[locale].billing.invoiceStates.failed));
    assert.match(html,/https:\/\/pay\.stripe\.com\/synthetic.pdf/);
    assert.ok(!html.includes('javascript:'));
  });
  test(`original feature controls retain card composition and accessible quantity labels in ${locale}`,async()=>{
    const html=await render(locale,'CustomPlanBuilder.jsx','CustomPlanBuilder',{
      features:[{id:'data_credits',code:'data_credits',type:'limit',name:'Data Credits',name_ar:'رصيد البيانات',unit:'credits',min:0}],
      configuration:{data_credits:{selected:true,limitValue:20}},onChange:()=>{},
    });
    assert.match(html,/ceopro-custom-feature-card is-selected/);
    assert.match(html,/ceopro-custom-quantity/);
    assert.match(html,/aria-label="(?:Data Credits|رصيد البيانات)"/);
    assert.match(html,/value="20"/);
    assert.ok(!html.includes('9007199254740991'), 'A technical number bound must not become a commercial allowance label');
  });
}
