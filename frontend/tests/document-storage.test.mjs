import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {getInvalidRagUploadFile,documentStorageStatus} from '../src/features/knowledge-base/utils/ragUploadContract.js';
test('RAG file picker accepts the same formats and 2 MiB boundary as the backend',()=>{
 for(const name of ['notes.txt','notes.md','notes.pdf','notes.docx','notes.xlsx'])assert.equal(getInvalidRagUploadFile([{name,size:2097152}]),null);
 for(const file of [{name:'photo.png',size:10},{name:'sales.csv',size:10},{name:'notes.txt',size:0},{name:'notes.txt',size:2097153}])assert.equal(getInvalidRagUploadFile([file]),file);
});
test('stored, indexed, pending, failed and unknown document states remain distinct',()=>{
 assert.equal(documentStorageStatus('Stored','on_demand'),'stored');
 assert.equal(documentStorageStatus('Processed','on_demand'),'stored');
 assert.equal(documentStorageStatus('Processed','indexed'),'ready');
 assert.equal(documentStorageStatus('Pending','on_demand'),'processing');
 assert.equal(documentStorageStatus('Failed','on_demand'),'failed');
 assert.equal(documentStorageStatus('other','on_demand'),'unknown');
});
test('storage, upload and deletion messages have Arabic/English key parity',()=>{
 const read=lang=>JSON.parse(readFileSync(new URL(`../src/assets/locales/${lang}.json`,import.meta.url))).ragAssistant;
 for(const group of ['storage','upload','documents','errors'])assert.deepEqual(Object.keys(read('en')[group]).sort(),Object.keys(read('ar')[group]).sort());
});
