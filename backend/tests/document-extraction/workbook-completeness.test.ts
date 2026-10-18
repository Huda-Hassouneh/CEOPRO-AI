import test from "node:test";
import assert from "node:assert/strict";
import * as xlsx from "xlsx";
import { extractCompleteSalesFile } from "../../src/modules/dataconnection/service/sales-csv-import.js";
test("canonical XLSX/XLSM preserve all 1200 rows, dates and stable sale IDs", () => {
  const book=xlsx.utils.book_new();
  const rows=[['product_name','quantity','unit_price','currency','transaction_date','sale_id','source_system'],
    ...Array.from({length:1200},(_,i)=>['Tea',1,10,'JOD',new Date('2026-10-01T00:00:00Z'),`line-${i}`,'pos'])];
  xlsx.utils.book_append_sheet(book,xlsx.utils.aoa_to_sheet(rows,{cellDates:true}),'Sales');
  for(const bookType of ['xlsx','xlsm'] as const){
    const result=extractCompleteSalesFile(`sales.${bookType}`,xlsx.write(book,{type:'buffer',bookType}));
    assert.equal(result.summary.row_outcomes.length,1200);assert.equal(result.rows_truncated_to_limit,false);
    assert.equal(result.summary.row_outcomes[1199]!.parse_result!.typed_fields.sale_id,'line-1199');
  }
  xlsx.utils.book_append_sheet(book,xlsx.utils.aoa_to_sheet([['Other'],['data']]),'Other');
  assert.throws(()=>extractCompleteSalesFile('sales.xlsx',xlsx.write(book,{type:'buffer',bookType:'xlsx'})),/exactly one/);
});
