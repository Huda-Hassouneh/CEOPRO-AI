import { getUnindexedRagDocuments, saveRagSearchContent } from "../repo/rag.repo.js";
import { extractSearchContent, searchRevision } from "./rag-search-text.js";

// Backfills pre-existing documents a small batch at a time. No file-count cutoff:
// every eligible document is considered before source ranking. Parsing happens
// outside database transactions, and indexed documents are not reparsed per query.
export async function ensureRagSearchIndex(input:{tenantId:string;userId:string}) {
  let after:string|undefined;
  for (;;) {
    const batch=await getUnindexedRagDocuments({...input,after});
    if (!batch.length) return;
    for (const document of batch) {
      const revision=searchRevision(document);
      const content=await extractSearchContent(document);
      await saveRagSearchContent({...input,document,revision,content});
    }
    after=batch[batch.length-1]!.document_id;
  }
}
