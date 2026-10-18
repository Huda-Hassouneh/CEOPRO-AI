import {readFileSync,readdirSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';
const root=fileURLToPath(new URL('../',import.meta.url));
const {files}=JSON.parse(readFileSync(path.join(root,'docs/TEAM_COMPETITOR_HASHES.json'),'utf8'));
for(const [name,expected] of Object.entries(files))assert.equal(createHash('sha256').update(readFileSync(path.join(root,'ai',name))).digest('hex'),expected,`Team file changed: ${name}`);
function walk(dir){return readdirSync(dir,{withFileTypes:true}).flatMap(e=>['__pycache__','.pytest_cache'].includes(e.name)?[]:e.isDirectory()?walk(path.join(dir,e.name)):[path.join(dir,e.name)]);}
const actual=walk(path.join(root,'ai/src/market_scraper')).map(p=>path.relative(path.join(root,'ai'),p).split(path.sep).join('/')).sort();
assert.deepEqual(actual,Object.keys(files).filter(p=>p.startsWith('src/market_scraper/')).sort(),'Custom files remain in the restored team subtree');
console.log(`Team competitor parity verified: ${Object.keys(files).length} byte-identical files; no custom scraper files remain.`);
