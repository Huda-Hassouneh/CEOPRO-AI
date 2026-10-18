import xlsx from "xlsx";
import { extname } from "node:path";
import { MAX_RAG_DOCUMENT_SIZE_BYTES, RAG_DOCUMENT_EXTENSIONS } from "../types/rag.types.js";
import {readBoundedOfficeArchive} from './rag-search-text.js';
export function ragUploadProblem(file: { originalname: string; size: number; buffer: Buffer }): string | null {
  const ext=extname(file.originalname).toLowerCase();
  if (!(RAG_DOCUMENT_EXTENSIONS as readonly string[]).includes(ext)) return "Unsupported document format.";
  if (!Buffer.isBuffer(file.buffer) || file.size !== file.buffer.length || file.size <= 0) return "Empty or inconsistent file size.";
  if (file.size > MAX_RAG_DOCUMENT_SIZE_BYTES) return "Document exceeds 2 MiB.";
  if (ext === ".pdf") return file.buffer.subarray(0,5).toString() === "%PDF-" ? null : "Invalid PDF signature.";
  if ([".xlsx",".docx"].includes(ext)) {
    if (file.buffer.subarray(0,2).toString() !== "PK") return "Invalid Office document signature.";
    try {
      // Read the ZIP directory rather than executing macros or trusting the extension.
      const zip=readBoundedOfficeArchive(file.buffer);
      const expected=ext === ".xlsx" ? "xl/workbook.xml" : "word/document.xml";
      if (!zip.FullPaths.some((path: string)=>path.endsWith('/'+expected) || path===expected)) return "Document contents do not match the file extension.";
    } catch { return "Malformed Office document."; }
    return null;
  }
  try { new TextDecoder("utf-8",{fatal:true}).decode(file.buffer); }
  catch { return "Text documents must use UTF-8."; }
  return file.buffer.includes(0) ? "Binary content is not a text document." : null;
}
