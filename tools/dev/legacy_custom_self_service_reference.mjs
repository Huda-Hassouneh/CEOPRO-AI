// Execute original decision functions in memory, substituting only repository reads.
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { stripTypeScriptTypes } from 'node:module';
import { createHash } from 'node:crypto';
const [root, input, output] = process.argv.slice(2);
const dir = resolve(root, 'src/modules/subscription/service');
const source = readFileSync(resolve(dir, 'custom-plan-configurator.service.ts'), 'utf8');
const policy = readFileSync(resolve(dir, 'custom-plan-policy.service.ts'), 'utf8');
const calculator = readFileSync(resolve(dir, 'custom-plan-pricing.service.ts'), 'utf8');
const payment = readFileSync(resolve(dir, 'custom-plan-payment-currency.service.ts'), 'utf8');
const runtime = pathToFileURL(resolve(root, 'node_modules/@prisma/client/runtime/client.mjs')).href;
const load = code => import('data:text/javascript;base64,' + Buffer.from(stripTypeScriptTypes(code, { mode: 'strip' })).toString('base64'));
const pricing = await load(calculator.replace('import { Prisma } from "../../../generated/prisma/client.js";', `import {Decimal} from ${JSON.stringify(runtime)}; const Prisma={Decimal};`));
const conversion = await load(payment.replace('import { Prisma } from "../../../generated/prisma/client.js";', `import {Decimal} from ${JSON.stringify(runtime)}; const Prisma={Decimal};`));
const helpers = source.slice(source.indexOf('function priceWithDiscount'), source.indexOf('function configurationHash'))
  + source.slice(source.indexOf('function mapPricingError'), source.indexOf('async function calculateConfiguration'));
const calculate = source.slice(source.indexOf('async function calculateConfiguration'), source.indexOf('export async function getCustomPlanConfigurator'));
const preview = source.slice(source.indexOf('export async function previewCustomPlanConfiguration'), source.indexOf('async function createOrReuseAutomaticQuote'));
const resolveLimit = policy.slice(policy.indexOf('export function resolveAutomaticFeatureLimit'));
const results = [];
for (const row of JSON.parse(readFileSync(input, 'utf8'))) {
  const code = `const data=${JSON.stringify(row)};
    const ERROR_CODES=new Proxy({}, {get:(_, key)=>key});
    const getCustomPlanPricingPolicy=async()=>data.policy;
    const customPlanRepository={getFeaturesByIds:async()=>data.definitions,getActiveVendorRates:async()=>data.vendorRates,
      getActiveInfrastructureRates:async()=>[],getVendorBackedFeatureIds:async()=>data.definitions.map(f=>f.id)};
    const calculateCustomPlanPrice=globalThis.__keelLegacyCalculator;
    ${resolveLimit}\n${helpers}\n${calculate}\n${preview}`;
  globalThis.__keelLegacyCalculator = pricing.calculateCustomPlanPrice;
  const actual = await (await load(code)).previewCustomPlanConfiguration(row.input);
  if (actual.success) actual.data.paymentAmount = conversion.convertCustomPlanAmountToPaymentCurrency({
    amount: actual.data.price, quoteCurrency: row.policy.currency, fxRate: row.policy.fxRate,
    fxSourceCurrency: row.policy.fxSourceCurrency, fxTargetCurrency: row.policy.fxTargetCurrency });
  results.push({ name: row.name, actual });
}
delete globalThis.__keelLegacyCalculator;
writeFileSync(output, JSON.stringify({ hashes: Object.fromEntries(Object.entries({source,policy,calculator,payment}).map(([k,v])=>[k,createHash('sha256').update(v).digest('hex')])),results }, null, 2));
