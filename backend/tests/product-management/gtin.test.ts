import test from 'node:test';
import assert from 'node:assert/strict';
import * as XLSX from 'xlsx';
import {validGtin,gtinKey} from '../../src/modules/products/service/gtin.js';
import {gtinSchema,productUpdateSchema} from '../../src/modules/products/types/products.validation.js';
import {parseGtinImport} from '../../src/modules/products/service/gtin-import.js';
test('GTIN lengths, check digit, leading zeros and optional API semantics',()=>{
 for(const value of ['96385074','036000291452','4006381333931','10012345000017'])assert.equal(validGtin(value),true,value);
 for(const value of ['96385075','036000291453','4006381333932','10012345000018','00000000','1234567','123456789','４００６３８１３３３９３１','4e12','4006 381333931'])assert.equal(validGtin(value),false,value);
 assert.equal(gtinSchema.parse(' 036000291452 '),'036000291452');
 assert.equal(gtinSchema.parse(''),null);assert.equal(gtinSchema.parse(null),null);assert.equal(gtinSchema.safeParse(36000291452).success,false);
 assert.equal(gtinKey('036000291452'),gtinKey('00036000291452'));
 assert.deepEqual(productUpdateSchema.parse({expectedVersion:1,price:'12'}),{expectedVersion:1,price:'12'});
 assert.deepEqual(productUpdateSchema.parse({expectedVersion:1,gtin:''}),{expectedVersion:1,gtin:null});
});
const csv=(text:string)=>({originalname:'gtins.csv',buffer:Buffer.from(text)});
test('CSV imports preserve digit strings and reject malformed or duplicate rows',()=>{
 assert.deepEqual(parseGtinImport(csv('sku,gtin\r\nTEA-1,036000291452\r\n')),[{sku:'TEA-1',gtin:'036000291452'}]);
 for(const content of ['sku,gtin\nA,4006381333932','sku,gtin\nA,','sku,gtin\nA,036000291452\na,036000291452','sku,gtin,price\nA,036000291452,1','sku,gtin\nA,3.6E+10','sku,gtin\n'])assert.throws(()=>parseGtinImport(csv(content)));
 assert.throws(()=>parseGtinImport(csv('sku,gtin\n'+Array.from({length:501},(_,i)=>`A${i},036000291452`).join('\n'))));
});
test('XLSX requires text cells and rejects numeric identifiers, formulas and oversized sheets',()=>{
 const file=(values:unknown[][],change?:(s:XLSX.WorkSheet)=>void)=>{
  const book=XLSX.utils.book_new(),sheet=XLSX.utils.aoa_to_sheet(values);change?.(sheet);XLSX.utils.book_append_sheet(book,sheet,'Products');
  return {originalname:'gtin.xlsx',buffer:Buffer.from(XLSX.write(book,{type:'buffer',bookType:'xlsx'}))};
 };
 assert.equal(parseGtinImport(file([['sku','gtin'],['A','036000291452']]))[0]!.gtin,'036000291452');
 assert.throws(()=>parseGtinImport(file([['sku','gtin'],['A',36000291452]])));
 assert.throws(()=>parseGtinImport(file([['sku','gtin'],['A','036000291452']],s=>{s.B2!.f='1+1';})));
 assert.throws(()=>parseGtinImport({originalname:'gtin.xlsx',buffer:Buffer.from('not zip')}));
});
