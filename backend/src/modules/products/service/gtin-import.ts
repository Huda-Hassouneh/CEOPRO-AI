import * as XLSX from 'xlsx';
import {inflateRawSync} from 'node:zlib';
import {validGtin} from './gtin.js';
import {ProductError} from '../types/products.types.js';
export const GTIN_IMPORT_BYTES=256*1024;
const fail=(reason:string,row?:number):never=>{throw new ProductError('INVALID_PARAMETER',{reason,row});};
// Bound ZIP expansion before invoking the spreadsheet parser.
function checkZip(b:Buffer){
 const end=b.lastIndexOf(Buffer.from([0x50,0x4b,0x05,0x06]));
 if(end<0 || end+22>b.length)fail('GTIN_IMPORT_FILE');
 const count=b.readUInt16LE(end+10),size=b.readUInt32LE(end+12),start=b.readUInt32LE(end+16);
 if(count>100 || count===0 || start+size>end || b.readUInt16LE(end+4)!==0 || b.readUInt16LE(end+6)!==0)fail('GTIN_IMPORT_FILE');
 let at=start,total=0;
 for(let n=0;n<count;n++){
  if(at+46>start+size || b.readUInt32LE(at)!==0x02014b50)fail('GTIN_IMPORT_FILE');
  total+=b.readUInt32LE(at+24);
  if(total>4*1024*1024 || (b.readUInt16LE(at+8)&1)!==0)fail('GTIN_IMPORT_FILE');
  const local=b.readUInt32LE(at+42),compressed=b.readUInt32LE(at+20),method=b.readUInt16LE(at+10);
  if(local+30>start || b.readUInt32LE(local)!==0x04034b50 || ![0,8].includes(method))fail('GTIN_IMPORT_FILE');
  const data=local+30+b.readUInt16LE(local+26)+b.readUInt16LE(local+28);
  if(data+compressed>start)fail('GTIN_IMPORT_FILE');
  const bytes=b.subarray(data,data+compressed);
  const expanded=method===0?bytes:inflateRawSync(bytes,{maxOutputLength:4*1024*1024});
  if(expanded.length!==b.readUInt32LE(at+24))fail('GTIN_IMPORT_FILE');
  at+=46+b.readUInt16LE(at+28)+b.readUInt16LE(at+30)+b.readUInt16LE(at+32);
 }
 if(at!==start+size)fail('GTIN_IMPORT_FILE');
}
export function parseGtinImport(file:{originalname:string;buffer:Buffer}){
 const ext=file.originalname.toLowerCase().split('.').at(-1);
 if(!file.buffer.length || file.buffer.length>GTIN_IMPORT_BYTES || !['csv','xlsx'].includes(ext ?? ''))fail('GTIN_IMPORT_FILE');
 let book:XLSX.WorkBook;
 try{
  if(ext==='xlsx')checkZip(file.buffer);
  if(ext==='csv' && file.buffer.includes(0))fail('GTIN_IMPORT_FILE');
  book=ext==='csv' ? XLSX.read(new TextDecoder('utf-8',{fatal:true}).decode(file.buffer),{type:'string',raw:true,sheetRows:502})
   :XLSX.read(file.buffer,{type:'buffer',sheetRows:502});
 }catch(error){if(error instanceof ProductError)throw error;return fail('GTIN_IMPORT_FILE');}
 if(book.SheetNames.length!==1)fail('GTIN_IMPORT_FILE');
 const sheet=book.Sheets[book.SheetNames[0]!]!;
 const range=XLSX.utils.decode_range(sheet['!fullref'] ?? sheet['!ref'] ?? 'A1');
 if(range.e.r>500 || range.e.c!==1 || range.s.r!==0 || range.s.c!==0)fail('GTIN_IMPORT_FILE');
 for(let r=0;r<=range.e.r;r++)for(let c=0;c<=1;c++){
  const cell=sheet[XLSX.utils.encode_cell({r,c})];
  if(cell && (cell.f || cell.F || cell.t!=='s'))fail('GTIN_IMPORT_TEXT',r+1);
 }
 const matrix=XLSX.utils.sheet_to_json<string[]>(sheet,{header:1,raw:true,defval:'',blankrows:false});
 const headers=matrix.shift()?.map(v=>v.trim().replace(/^\uFEFF/,'').toLowerCase());
 if(headers?.length!==2 || !headers.includes('sku') || !headers.includes('gtin'))fail('GTIN_IMPORT_FILE');
 const seen=new Set<string>();
 const rows=matrix.map((values,index)=>{
  const sku=(values[headers!.indexOf('sku')] ?? '').trim(),gtin=(values[headers!.indexOf('gtin')] ?? '').trim();
  if(!/^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/.test(sku) || !validGtin(gtin) || seen.has(sku.toLowerCase()))fail('GTIN_IMPORT_ROW',index+2);
  seen.add(sku.toLowerCase());return {sku,gtin};
 });
 if(!rows.length)fail('GTIN_IMPORT_FILE');
 return rows;
}
