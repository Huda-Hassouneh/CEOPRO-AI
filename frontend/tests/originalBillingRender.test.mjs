// Synthetic presentation fixtures only; production pages always use Python APIs.
import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { createServer } from 'vite';
import { mapPlan } from '../src/features/billing/api/billingApi.js';
import { toOriginalPlan } from '../src/features/billing/api/originalBillingModel.js';
import { formatMoney } from '../src/features/billing/utils/money.js';
let vite;
test.before(async()=>{vite=await createServer({server:{middlewareMode:true},appType:'custom',logLevel:'silent'});});
test.after(async()=>{await vite.close();});
async function render(locale, file, name, props) {
  const {loadLocale}=await vite.ssrLoadModule('/src/shared/lib/i18n.js');
  await loadLocale(locale);
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
  for(const days of [14,7,0]){
    test(`configured ${days}-day trial is distinct from an existing expiry in ${locale}`,async()=>{
      const configured=toOriginalPlan(mapPlan({plan_key:'starter',name:{en:'Standard',ar:'ستاندرد'},trial_days:days,self_serve:true,monthly_price:29,currency:'USD',prices:[{period_code:'monthly',interval_months:1,amount:29,currency:'USD',discount_percent:0,purchasable:true}]}));
      const {translate}=await vite.ssrLoadModule('/src/shared/lib/i18n.js');
      const originalNow=Date.now;
      // Almost a day has already elapsed; configured length must not become 13/6.
      Date.now=()=>Date.parse('2026-11-03T07:37:19Z');
      let html;
      try{
        html=await render(locale,'PlanSummaryCard.jsx','PlanSummaryCard',{plan:configured,billingPeriod:'monthly',checkoutMode:days?'trial':'paid',checkoutTrialEndsAt:days?Date.parse('2026-11-16T07:37:20Z')/1000:null});
      }finally{Date.now=originalNow;}
      const expected=translate(locale,days?'billing.payment.trial':'billing.payment.noTrial',{days});
      assert.ok(html.includes(expected));
      if(days){
        assert.ok(html.includes(translate(locale,'billing.payment.existingTrial')));
        assert.ok(html.includes('UTC'));
        const card=await render(locale,'OriginalPlanCard.jsx','PlanCard',{plan:configured,billingPeriod:'monthly',onSelect(){}});
        assert.ok(card.includes(String(days)));
      }else assert.ok(!html.includes(translate(locale,'billing.payment.existingTrial')));
    });
  }
  test(`previously issued trial remains visible even if selected plan offers no new trial in ${locale}`,async()=>{
    const html=await render(locale,'PlanSummaryCard.jsx','PlanSummaryCard',{plan:{trialDays:0,basePrice:29,currency:'USD'},checkoutMode:'trial',checkoutTrialEndsAt:Date.parse('2026-11-16T07:37:20Z')/1000});
    const {translate}=await vite.ssrLoadModule('/src/shared/lib/i18n.js');
    assert.ok(html.includes(translate(locale,'billing.payment.noTrial')));
    assert.ok(html.includes(translate(locale,'billing.payment.existingTrial')));
  });
  const plan = toOriginalPlan(mapPlan({
    plan_key: 'starter', name: { en: 'Standard', ar: 'ستاندرد' }, self_serve: true,
    monthly_price: 29, currency: 'USD', limits: { tracked_products: 100, ai_credits: 500 },
    feature_catalog: {
      tracked_products: { name: 'Products', name_ar: 'المنتجات', unit: 'products', category: { key: 'business', label_en: 'Business Operations', label_ar: 'عمليات الأعمال', display_order: 1 } },
      ai_credits: { name: 'AI Credits', name_ar: 'أرصدة الذكاء الاصطناعي', unit: 'credits', category: { key: 'ai', label_en: 'AI & Automation', label_ar: 'الذكاء الاصطناعي والأتمتة', display_order: 2 } },
    },
    entitlements: ['market_intelligence', 'demand_prediction', 'competitor_management'],
    prices: [{ period_code: 'three-months', interval_months: 3, amount: 87, currency: 'USD', discount_percent: 0, purchasable: true }],
  }));
  test(`launch pricing preserves main's redesigned card and term totals in ${locale}`, async () => {
    const html = await render(locale, 'OriginalPlanCard.jsx', 'PlanCard', { plan, billingPeriod: 'three-months', onSelect() {} });
    assert.match(html, /ceopro-plan-card__amount/);
    assert.match(html, /ceopro-plan-card__credits/);
    assert.ok(html.includes(formatMoney(29, 'USD', locale, { compact: true })));
    assert.ok(html.includes(formatMoney(87, 'USD', locale, { compact: true })));
    assert.doesNotMatch(html, /10%|20%/);
  });
  test(`full plan comparison retains canonical categories and quantities in ${locale}`, async () => {
    const html = await render(locale, 'PlanComparisonTable.jsx', 'PlanComparisonTable', { plans: [plan] });
    assert.match(html, /scope="colgroup" colSpan="2"/);
    for (const category of ['tracked_products', 'ai_credits'].map(code => plan.features[code].category)) {
      assert.ok(html.includes(locale === 'ar' ? category.label_ar : category.label_en.replace('&', '&amp;')));
    }
    assert.ok(html.includes(new Intl.NumberFormat(locale === 'ar' ? 'ar-JO' : 'en-US').format(100)));
  });
  test(`subscription review renders the tenant-scoped backend preview and its payment policy in ${locale}`,async()=>{
    const html=await render(locale,'PlanChangePreview.jsx','PlanChangePreview',{
      subscription:{hasStripeSubscription:true},preview:{data:{timing:'period_end',payment_policy:'next_period_price',feature_changes:[{feature_code:'tracked_products',before:250,after:100,over_limit:true}],effective_at:'2026-11-25T12:00:00Z'}},
    });
    assert.match(html,/250/);assert.match(html,/100/);
    assert.ok(!html.includes('billing.customPlan.featureNames.'));
    assert.ok(!html.includes('$0'));
  });
  test(`original invoice table renders historical amounts and safe documents in ${locale}`,async()=>{
    const {loadLocale,translate}=await vite.ssrLoadModule('/src/shared/lib/i18n.js');
    await loadLocale(locale);
    const t=(key)=>translate(locale,key);
    const html=await render(locale,'InvoiceHistoryTable.jsx','InvoiceHistoryTable',{locale,t,invoices:[
      {id:'in_synthetic',amount:52.75,currency:'USD',date:'2026-10-25',type:'subscription',paymentStatus:'failed',pdfUrl:'https://pay.stripe.com/synthetic.pdf'},
      {id:'in_unsafe',amount:10,currency:'USD',date:'2026-10-24',type:'subscription',paymentStatus:'paid',pdfUrl:'javascript:alert(1)'},
    ]});
    assert.match(html,/billing-invoice-table/);
    assert.ok(html.includes(t('billing.invoiceStates.failed')));
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
