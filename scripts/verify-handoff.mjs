import assert from 'node:assert/strict';
import {readFileSync,readdirSync,existsSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {parseEnv} from 'node:util';
const root=fileURLToPath(new URL('../',import.meta.url));
const ignored=new Set(['node_modules','.venv','__pycache__','dist','.git','.pytest_cache']);
function walk(dir){return readdirSync(dir,{withFileTypes:true}).flatMap(e=>ignored.has(e.name)||e.isSymbolicLink()?[]:e.isDirectory()?walk(path.join(dir,e.name)):[path.join(dir,e.name)]);}
const files=walk(root);
// Imported team documentation is preserved as reference, not rewritten by this review.
const docs=files.filter(p=>p.endsWith('.md')&&!p.startsWith(path.join(root,'reference')+path.sep)&&(!p.startsWith(path.join(root,'ai')+path.sep)||path.basename(p)==='README.md'));
for(const p of docs){
 const source=readFileSync(p,'utf8');
 for(const m of source.matchAll(/\[[^\]]*\]\(([^)]+)\)/g)){
  const url=m[1].split('#')[0];
  if(!url||/^(https?:|mailto:)/.test(url))continue;
  assert.ok(existsSync(path.resolve(path.dirname(p),decodeURIComponent(url))),`Broken link in ${path.relative(root,p)}: ${url}`);
 }
}
const sourceMap=JSON.parse(readFileSync(path.join(root,'docs/ENVIRONMENT_SOURCE_MAP.json'),'utf8'));
for(const area of ['root','backend','frontend','ai']){
 const example=readFileSync(path.join(root,area==='root'?'':area,'.env.example'),'utf8');
 const definitions=new Set([...example.matchAll(/^\s*(?:#\s*)?([A-Z][A-Z0-9_]+)=/gm)].map(m=>m[1]));
 for(const key of Object.keys(sourceMap[area]))assert.ok(definitions.has(key),`${area} example missing ${key}`);
 assert.doesNotThrow(()=>parseEnv(example));
}
assert.ok(!files.some(p=>{const name=path.basename(p);return (name==='.env'||name.startsWith('.env.'))&&!name.endsWith('.example');}), 'Actual env files must not be packaged');
const rootPackage=JSON.parse(readFileSync(path.join(root,'package.json')));
for(const command of Object.values(rootPackage.scripts)){
 const m=command.match(/^npm --prefix (\w+) run ([\w:-]+)/);
 if(m){const pkg=JSON.parse(readFileSync(path.join(root,m[1],'package.json')));assert.ok(pkg.scripts[m[2]],`Missing delegated script: ${command}`);}
}
assert.equal(readFileSync(path.join(root,'backend/prisma/migrations/migration_lock.toml'),'utf8').includes('provider = "postgresql"'),true);
console.log(`Handoff checks passed: ${docs.length} integrated Markdown files (imported reference documentation excluded), relative links, four environment examples and delegated scripts.`);
