import { extname } from "node:path";
import { createHash } from "node:crypto";
import xlsx from "xlsx";
import { XMLParser } from "fast-xml-parser";

export const RAG_SEARCH_VERSION = 2;
const MAX_TEXT_BYTES = 8 * 1024 * 1024;
const MAX_OFFICE_UNPACKED_BYTES = 32 * 1024 * 1024;
export type SearchContent = { text: string; state: "ready" | "empty" | "unreadable" };
// Installation/runtime failures are not evidence of an invalid customer file.
export class RagDocumentProcessingError extends Error {
  constructor(cause: unknown) {
    super("The server could not run its PDF text extractor.", {cause});
    this.name = "RagDocumentProcessingError";
  }
}
export type SearchDocument = {
  document_id: string; file_name: string; storage_bucket_path: string;
  processed_status: string; source_file_content: Uint8Array | null;
  rag_document_chunks: Array<{ chunk_text_content: string }>;
};
export function searchRevision(document: SearchDocument): string {
  const hash = createHash("sha256");
  hash.update(JSON.stringify([document.file_name, document.storage_bucket_path, document.processed_status]));
  if (document.source_file_content) hash.update(document.source_file_content);
  else hash.update(JSON.stringify(document.rag_document_chunks));
  return hash.digest("hex");
}
export function normalizeSearchText(text: string): string {
  return text.normalize("NFKC").toLowerCase().replace(/[\u064B-\u065F\u0670\u0640]/g, "")
    .replace(/[أإآٱ]/g, "ا").replace(/ى/g, "ي").replace(/\0/g, "");
}
const STOP_WORDS = new Set(("a an the is are was were be been to of for and or in on at by with from it this that " +
  "what which who when where how do does did can could would should my our your please tell me about " +
  "ما ماذا هل كيف اين متي من في علي الي عن هذا هذه هو هي ان او و كم لدي عند").split(/\s+/));
export function searchQuery(question: string): string {
  const words = normalizeSearchText(question).match(/[\p{L}\p{N}]+/gu) ?? [];
  return [...new Set(words.filter(word => word.length > 1 && !STOP_WORDS.has(word)))].slice(0,64)
    .map(word => `'${word}'`).join(" | ");
}
export function searchPassages(fileName: string, text: string): string[] {
  const result: string[] = [];
  // Overlap keeps a phrase crossing a boundary searchable. Full original content
  // is still sent to the AI; these passages only rank source documents locally.
  for (let offset = 0; offset < text.length; offset += 1800) {
    result.push(normalizeSearchText(`${fileName}\n${text.slice(offset, offset + 2000)}`));
  }
  return result.length ? result : [normalizeSearchText(fileName)];
}
function checked(text: string): string {
  if (Buffer.byteLength(text, "utf8") > MAX_TEXT_BYTES) throw new Error("Search text exceeds 8 MiB.");
  return text.replace(/\0/g, "").trim();
}
export function readBoundedOfficeArchive(buffer: Buffer) {
  // Inspect central-directory sizes before the existing XLSX library inflates ZIPs.
  let eocd = -1;
  for (let i = buffer.length - 22; i >= Math.max(0,buffer.length-65557); i--) {
    if (buffer.readUInt32LE(i) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) throw new Error("Missing ZIP directory.");
  const count = buffer.readUInt16LE(eocd+10);
  let offset = buffer.readUInt32LE(eocd+16), total = 0;
  if (count === 65535 || offset === 0xffffffff) throw new Error("ZIP64 is not supported for search.");
  for (let n = 0; n < count; n++) {
    if (offset+46 > buffer.length || buffer.readUInt32LE(offset) !== 0x02014b50) throw new Error("Invalid ZIP directory.");
    const size = buffer.readUInt32LE(offset+24);
    total += size;
    if (size === 0xffffffff || total > MAX_OFFICE_UNPACKED_BYTES) throw new Error("Office archive exceeds search extraction budget.");
    offset += 46 + buffer.readUInt16LE(offset+28) + buffer.readUInt16LE(offset+30) + buffer.readUInt16LE(offset+32);
  }
  return xlsx.CFB.read(buffer,{type:"buffer"}) as {FullPaths:string[];FileIndex:Array<{content:Uint8Array}>};
}
function xmlText(xml: string): string {
  // No DTD or custom entities. Preserve order so table/paragraph content is not
  // grouped by tag name. The parser decodes normal XML character entities.
  if (/<!DOCTYPE|<!ENTITY/i.test(xml)) throw new Error("XML declarations are not supported.");
  const nodes = new XMLParser({preserveOrder:true,ignoreAttributes:true,trimValues:false,parseTagValue:false}).parse(xml);
  const parts: string[] = [];
  const walk = (value: unknown): void => {
    if (Array.isArray(value)) { for (const item of value) walk(item); return; }
    if (value && typeof value === "object") for (const [key,child] of Object.entries(value)) {
      if (key === "#text") parts.push(String(child));
      else { walk(child); if (["w:p","w:tc","w:tr"].includes(key)) parts.push("\n"); }
    }
  };
  walk(nodes); return parts.join("");
}
export async function extractSearchContent(document: Pick<SearchDocument,"file_name"|"source_file_content"|"rag_document_chunks">): Promise<SearchContent> {
  try {
    let text = "";
    if (!document.source_file_content) text = document.rag_document_chunks.map(c=>c.chunk_text_content).join("\n\n");
    else {
      const bytes = Buffer.from(document.source_file_content);
      switch(extname(document.file_name).toLowerCase()) {
        case ".txt": case ".md": text = new TextDecoder("utf-8",{fatal:true}).decode(bytes); break;
        case ".pdf": {
          let getDocument: typeof import("pdfjs-dist/legacy/build/pdf.mjs").getDocument;
          try { ({getDocument} = await import("pdfjs-dist/legacy/build/pdf.mjs")); }
          catch (cause) { throw new RagDocumentProcessingError(cause); }
          let task: ReturnType<typeof getDocument> | undefined;
          try {
            task = getDocument({data:new Uint8Array(bytes),useSystemFonts:true,verbosity:0});
            const pdf = await task.promise;
            if (pdf.numPages > 2000) throw new Error("PDF exceeds search page budget.");
            for(let i=1;i<=pdf.numPages;i++) {
              const page = await pdf.getPage(i);
              const content = await page.getTextContent();
              text += content.items.map(item=>"str" in item ? item.str + (item.hasEOL ? "\n" : " ") : "").join("") + "\n";
              checked(text);page.cleanup();
            }
          } catch (cause) {
            if (cause instanceof Error && (
              ["InvalidPDFException", "PasswordException"].includes(cause.name) ||
              cause.message === "PDF exceeds search page budget." ||
              cause.message === "Search text exceeds 8 MiB."
            )) throw cause;
            throw new RagDocumentProcessingError(cause);
          } finally { await task?.destroy(); }
          break;
        }
        case ".docx": {
          const archive = readBoundedOfficeArchive(bytes);
          const parts = archive.FullPaths.map((path,i)=>({path,entry:archive.FileIndex[i]}))
            .filter(({path})=>/word\/(document|header\d+|footer\d+|footnotes|endnotes)\.xml$/.test(path));
          if (!parts.some(({path})=>path.endsWith("word/document.xml"))) throw new Error("Missing document XML.");
          text = parts.map(({entry})=>xmlText(Buffer.from(entry!.content).toString("utf8"))).join("\n");break;
        }
        case ".xlsx": {
          readBoundedOfficeArchive(bytes);
          const workbook = xlsx.read(bytes,{type:"buffer",cellDates:true});
          text = workbook.SheetNames.map(name=>`${name}\n${xlsx.utils.sheet_to_csv(workbook.Sheets[name]!)}`).join("\n\n");break;
        }
        default: throw new Error("Unsupported search format.");
      }
    }
    text = checked(text);
    return {text,state:text ? "ready" : "empty"};
  } catch (error) {
    if (error instanceof RagDocumentProcessingError) throw error;
    // Keep the original file available; searchable filename is retained, but
    // corrupt, encrypted and image-only content must never become invented text.
    return {text:"",state:"unreadable"};
  }
}
