import assert from 'node:assert/strict';
import test from 'node:test';
import * as xlsx from 'xlsx';
import {ragUploadProblem} from '../../src/modules/rag/service/rag-upload.validation.ts';
const file=(name,bytes)=>({originalname:name,buffer:bytes,size:bytes.length});
test('RAG validation aligns supported formats, exact 2 MiB boundary and actual bytes',()=>{
 assert.equal(ragUploadProblem(file('note.md',Buffer.alloc(2*1024*1024,65))),null);
 assert.match(ragUploadProblem(file('note.txt',Buffer.alloc(2*1024*1024+1,65))),/2 MiB/);
 assert.match(ragUploadProblem({...file('note.txt',Buffer.from('text')),size:100}),/inconsistent/);
 for(const name of ['image.png','sales.csv','sheet.xlsm'])assert.match(ragUploadProblem(file(name,Buffer.from('data'))),/Unsupported/);
 assert.match(ragUploadProblem(file('note.txt',Buffer.from([255,254]))),/UTF-8/);
 assert.match(ragUploadProblem(file('note.txt',Buffer.from([65,0]))),/Binary/);
 assert.match(ragUploadProblem(file('note.pdf',Buffer.from('pretend'))),/signature/);
 assert.equal(ragUploadProblem(file('note.pdf',Buffer.from('%PDF-1.7\n'))),null);
});
test('Office extensions must match the actual ZIP document type',()=>{
 const book=xlsx.utils.book_new();xlsx.utils.book_append_sheet(book,xlsx.utils.aoa_to_sheet([['Document'],['Text']]),'Notes');
 const bytes=xlsx.write(book,{type:'buffer',bookType:'xlsx'});
 assert.equal(ragUploadProblem(file('notes.xlsx',bytes)),null);
 assert.match(ragUploadProblem(file('notes.docx',bytes)),/contents/);
 assert.match(ragUploadProblem(file('bad.docx',Buffer.from('PKbroken'))),/Malformed|contents/);
});
