// Execute a disposable in-memory copy of the actual read-only Node calculator.
import {readFileSync,writeFileSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {stripTypeScriptTypes} from 'node:module';
import {createHash} from 'node:crypto';
const [legacy,input,output]=process.argv.slice(2);
if(!legacy||!input||!output)throw new Error('Usage: node legacy_billing_reference.mjs <legacy backend> <vectors JSON> <output JSON>');
const file=resolve(legacy,'src/modules/subscription/service/custom-plan-pricing.service.ts');
const source=readFileSync(file,'utf8');
const runtime=pathToFileURL(resolve(legacy,'node_modules/@prisma/client/runtime/client.mjs')).href;
const copied=source.replace('import { Prisma } from "../../../generated/prisma/client.js";',`import {Decimal} from ${JSON.stringify(runtime)}; const Prisma={Decimal};`);
const js=stripTypeScriptTypes(copied,{mode:'strip'});
const module=await import('data:text/javascript;base64,'+Buffer.from(js).toString('base64'));
const vectors=JSON.parse(readFileSync(input,'utf8'));
const results=vectors.map(v=>{try{return{name:v.name,status:'calculated',result:module.calculateCustomPlanPrice(v.input)}}catch(e){return{name:v.name,status:'rejected',error:e.message}}});
writeFileSync(output,JSON.stringify({source:file,sha256:createHash('sha256').update(source).digest('hex'),execution:'In-memory copy; original Prisma Decimal; no writes or backend process in legacy repository',results},null,2));
console.log('Executed '+results.length+' original Node vectors without modifying the reference repository.');
