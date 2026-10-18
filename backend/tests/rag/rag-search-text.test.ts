import test from 'node:test';
import assert from 'node:assert/strict';
import {extractSearchContent,normalizeSearchText,searchQuery,searchPassages} from '../../src/modules/rag/service/rag-search-text.js';
import {docxFixture,pdfFixture,xlsxFixture} from './search-fixtures.js';

test('extracts actual TXT, Markdown, PDF, DOCX and every XLSX worksheet',async()=>{
 for(const [file_name,bytes,expected] of [
  ['a.txt',Buffer.from('Zephyr supplier sells tea'),'Zephyr'],
  ['a.md',Buffer.from('# Delivery\nFree over 25 JOD'),'25 JOD'],
  ['a.pdf',pdfFixture('Nebula returns allowed within 9 days'),'Nebula returns'],
  ['a.docx',docxFixture('Orion &amp; Cedar supply rice'),'Orion & Cedar'],
  ['a.xlsx',xlsxFixture(),'Cobalt Foods']
 ] as const){
  const result=await extractSearchContent({file_name,source_file_content:bytes,rag_document_chunks:[]});
  assert.equal(result.state,'ready',file_name);assert.ok(result.text.includes(expected),`${file_name}: ${result.text}`);
  if(file_name.endsWith('xlsx'))assert.match(result.text,/Saffron delivery/);
 }
});
test('corrupt/encrypted inputs are not fabricated; existing external chunks remain searchable',async()=>{
 assert.equal((await extractSearchContent({file_name:'broken.pdf',source_file_content:Buffer.from('%PDF-broken'),rag_document_chunks:[]})).state,'unreadable');
 const chunks=await extractSearchContent({file_name:'external.pdf',source_file_content:null,rag_document_chunks:[{chunk_text_content:'Historic delivery agreement'}]});
 assert.equal(chunks.state,'ready');assert.match(chunks.text,/Historic/);
});
test('English/Arabic normalization, safe query syntax, and boundary overlap',()=>{
 assert.equal(normalizeSearchText('إِيصَال أَرْز'),'ايصال ارز');
 assert.equal(searchQuery("What is our delivery fee? | ! '"),"'delivery' | 'fee'");
 assert.equal(searchQuery('ما هي أسعار الأرز؟'),"'اسعار' | 'الارز'");
 assert.equal(searchQuery('What is it?'),'');
 const parts=searchPassages('notes.txt','x'.repeat(1790)+' rare rice delivery '+'y'.repeat(1000));
 assert.equal(parts.length,2);assert.ok(parts[0]?.includes('rare rice delivery'));
});
