// No database access, API requests or usage charges. Run against the exact file
// rejected by upload, under the same Node installation used by npm run dev.
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';

console.log(`Node ${process.version}; ${process.platform}/${process.arch}`);
console.log('Installed PDF.js:', JSON.parse(await readFile(new URL('../../node_modules/pdfjs-dist/package.json', import.meta.url))).version);
console.log('PDF.js engine requirement:', JSON.parse(await readFile(new URL('../../node_modules/pdfjs-dist/package.json', import.meta.url))).engines.node);
const path=process.argv[2];
if (!path) {console.error('Usage: node scripts/rag/check-pdf.mjs "C:\\path\\Market_Brief_01.pdf"');process.exitCode=1;}
else {
  let task;
  try {
    const bytes=await readFile(resolve(path));
    if (bytes.length===0 || bytes.length>2*1024*1024 || bytes.subarray(0,5).toString()!=='%PDF-') throw new Error('Empty/oversized file or invalid PDF signature.');
    const {getDocument}=await import('pdfjs-dist/legacy/build/pdf.mjs');
    task=getDocument({data:new Uint8Array(bytes),useSystemFonts:true,verbosity:0});
    const pdf=await task.promise;
    if(pdf.numPages>2000)throw new Error('PDF exceeds search page budget.');
    let length=0;
    for(let n=1;n<=pdf.numPages;n++){
      const page=await pdf.getPage(n),content=await page.getTextContent();
      length+=content.items.reduce((sum,item)=>sum+('str' in item?Buffer.byteLength(item.str,'utf8'):0),0);page.cleanup();
      if(length>8*1024*1024)throw new Error('Search text exceeds 8 MiB.');
    }
    console.log(`PASS: ${bytes.length} bytes, ${pdf.numPages} pages, ${length} extracted text bytes.`);
  } catch(error) {console.error('PDF EXTRACTION FAILED:', error);process.exitCode=1;}
  finally {await task?.destroy();}
}
