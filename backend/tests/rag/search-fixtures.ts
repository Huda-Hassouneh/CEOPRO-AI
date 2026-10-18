import xlsx from 'xlsx';
export function docxFixture(text:string):Buffer {
  const zip=xlsx.CFB.utils.cfb_new();
  xlsx.CFB.utils.cfb_add(zip,'[Content_Types].xml',Buffer.from('<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'));
  xlsx.CFB.utils.cfb_add(zip,'word/document.xml',Buffer.from(`<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>${text}</w:t></w:r></w:p></w:body></w:document>`));
  return Buffer.from(xlsx.CFB.write(zip,{type:'buffer',fileType:'zip'}));
}
export function xlsxFixture():Buffer {
  const book=xlsx.utils.book_new();
  xlsx.utils.book_append_sheet(book,xlsx.utils.aoa_to_sheet([['SKU','Supplier'],['ORCHID-5','Cobalt Foods']]),'Suppliers');
  xlsx.utils.book_append_sheet(book,xlsx.utils.aoa_to_sheet([['Policy'],['Saffron delivery costs 3 JOD']]),'Policies');
  return xlsx.write(book,{type:'buffer',bookType:'xlsx'});
}
export function pdfFixture(text:string):Buffer {
  const objects=[
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 400] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'
  ];
  const stream=`BT /F1 12 Tf 30 350 Td (${text.replace(/[()\\]/g,'\\$&')}) Tj ET`;
  objects.push(`<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}\nendstream`);
  let pdf='%PDF-1.4\n';const offsets=[0];
  objects.forEach((object,i)=>{offsets.push(Buffer.byteLength(pdf));pdf+=`${i+1} 0 obj\n${object}\nendobj\n`;});
  const xref=Buffer.byteLength(pdf);pdf+=`xref\n0 ${objects.length+1}\n0000000000 65535 f \n`;
  for(const offset of offsets.slice(1))pdf+=`${String(offset).padStart(10,'0')} 00000 n \n`;
  pdf+=`trailer\n<< /Size ${objects.length+1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
  return Buffer.from(pdf);
}
