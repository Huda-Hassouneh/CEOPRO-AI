import { prisma } from "../../../config/database.js";
import type { Prisma } from "../../../generated/prisma/client.js";
import { getFeatureAccessInfo, reserveFeatureUsageInTransaction } from "../../features/repo/usage.repo.js";
import type { RagDocumentStatus } from "../types/rag.types.js";
import { RAG_SEARCH_VERSION, searchPassages, searchQuery, searchRevision, type SearchContent, type SearchDocument } from "../service/rag-search-text.js";

async function setTenantContext(
  tx: Prisma.TransactionClient,
  tenantId: string,
  userId: string
): Promise<void> {
  await tx.$queryRaw`
    SELECT
      set_config('app.current_tenant_id', ${tenantId}, true),
      set_config('app.current_user_id', ${userId}, true)
  `;
}

export async function listRagDocuments(input: {
  tenantId: string;
  userId: string;
  page: number;
  pageSize: number;
}) {
  return prisma.$transaction(async (tx) => {
    await setTenantContext(tx, input.tenantId, input.userId);
    return tx.rag_documents_metadata.findMany({
      where: { tenant_id: input.tenantId },
      orderBy: { uploaded_at: "desc" },
      skip: (input.page - 1) * input.pageSize,
      take: input.pageSize,
      select: {
        document_id: true,
        file_name: true,
        file_size_bytes: true,
        storage_bucket_path: true,
        content_type: true,
        uploaded_by_user_id: true,
        uploaded_at: true,
        processed_status: true
      }
    });
  });
}

export async function countRagDocuments(input: {
  tenantId: string;
  userId: string;
}) {
  return prisma.$transaction(async (tx) => {
    await setTenantContext(tx, input.tenantId, input.userId);
    return tx.rag_documents_metadata.count({
      where: { tenant_id: input.tenantId }
    });
  });
}

export async function getRagQueryDocuments(input: {
  tenantId: string;
  userId: string;
  limit: number;
  queryText?: string;
}) {
  return prisma.$transaction(async (tx) => {
    await setTenantContext(tx, input.tenantId, input.userId);
    const query = searchQuery(input.queryText ?? "");
    const terms = JSON.stringify(query ? query.split(" | ") : []);
    const ranked = await tx.$queryRaw<Array<{document_id:string}>>`
      WITH q AS (SELECT to_tsquery('simple', ${query}) || to_tsquery('english', ${query}) AS terms),
      keywords AS MATERIALIZED (
        SELECT value AS word, to_tsquery('simple',value) || to_tsquery('english',value) AS terms
        FROM jsonb_array_elements_text(${terms}::jsonb)
      ),
      scores AS (
        SELECT p.document_id, count(DISTINCT k.word) AS matched_terms,
          max(ts_rank_cd(p.search_vector,q.terms)) AS relevance
        FROM public.rag_document_search_passages p CROSS JOIN q
        JOIN keywords k ON p.search_vector @@ k.terms
        WHERE p.tenant_id=${input.tenantId}::uuid AND p.search_vector @@ q.terms
        GROUP BY p.document_id
      )
      SELECT d.document_id FROM public.rag_documents_metadata d
      LEFT JOIN scores s ON s.document_id=d.document_id
      WHERE d.tenant_id=${input.tenantId}::uuid AND d.processed_status IN ('Stored','Processed')
        AND EXISTS(SELECT 1 FROM public.rag_document_search idx WHERE idx.tenant_id=d.tenant_id
          AND idx.document_id=d.document_id AND idx.index_version=${RAG_SEARCH_VERSION}
          AND idx.content_state='ready' AND btrim(idx.source_text)<>'')
        AND (NOT starts_with(d.storage_bucket_path,'_generated/')
          OR starts_with(d.storage_bucket_path, ${`_generated/${input.tenantId}/`}))
        AND (d.source_file_content IS NOT NULL OR EXISTS (
          SELECT 1 FROM public.rag_document_chunks c WHERE c.tenant_id=d.tenant_id AND c.document_id=d.document_id
            AND btrim(c.chunk_text_content) <> ''
        ))
      ORDER BY coalesce(s.matched_terms,0) DESC, coalesce(s.relevance,0) DESC,
        d.uploaded_at DESC NULLS LAST, d.document_id DESC
      LIMIT ${Math.min(10,Math.max(1,input.limit))}
    `;
    const documents = await tx.rag_documents_metadata.findMany({
      where: {
        tenant_id: input.tenantId,
        document_id: {in:ranked.map(row=>row.document_id)},
        processed_status: { in: ["Stored", "Processed"] },
        OR: [{storage_bucket_path:{not:{startsWith:"_generated/"}}},
          {storage_bucket_path:{startsWith:`_generated/${input.tenantId}/`}}]
      },
      select: {
        document_id: true,
        file_name: true,
        content_type: true,
        source_file_content: true,
        search_index: {select:{source_text:true,source_revision:true,content_state:true,index_version:true}},
        rag_document_chunks: {
          orderBy: { chunk_index: "asc" },
          select: { chunk_text_content: true }
        }
      }
    });
    const byId = new Map(documents.map(document=>[document.document_id,document]));
    return ranked.flatMap(row=>{const document=byId.get(row.document_id);return document ? [document] : [];});
  });
}

const searchDocumentSelect = {
  document_id:true,file_name:true,storage_bucket_path:true,processed_status:true,source_file_content:true,
  rag_document_chunks:{orderBy:{chunk_index:"asc" as const},select:{chunk_text_content:true}}
} as const;

export async function getUnindexedRagDocuments(input:{tenantId:string;userId:string;after?:string}):Promise<SearchDocument[]> {
  return prisma.$transaction(async tx=>{
    await setTenantContext(tx,input.tenantId,input.userId);
    const rows=await tx.$queryRaw<Array<{document_id:string}>>`
      SELECT d.document_id FROM public.rag_documents_metadata d
      WHERE d.tenant_id=${input.tenantId}::uuid AND d.processed_status IN ('Stored','Processed')
        AND (${input.after ?? null}::uuid IS NULL OR d.document_id > ${input.after ?? null}::uuid)
        AND (NOT starts_with(d.storage_bucket_path,'_generated/') OR starts_with(d.storage_bucket_path,${`_generated/${input.tenantId}/`}))
        AND NOT EXISTS (SELECT 1 FROM public.rag_document_search s
          WHERE s.tenant_id=d.tenant_id AND s.document_id=d.document_id AND s.index_version=${RAG_SEARCH_VERSION})
      ORDER BY d.document_id LIMIT 8
    `;
    const documents=await tx.rag_documents_metadata.findMany({
      where:{tenant_id:input.tenantId,document_id:{in:rows.map(row=>row.document_id)}},select:searchDocumentSelect
    });
    return documents.sort((a,b)=>a.document_id.localeCompare(b.document_id));
  });
}

async function replaceSearchContent(tx:Prisma.TransactionClient,input:{tenantId:string;documentId:string;fileName:string;content:SearchContent;revision:string}) {
  await tx.$executeRaw`DELETE FROM public.rag_document_search WHERE tenant_id=${input.tenantId}::uuid AND document_id=${input.documentId}::uuid`;
  await tx.$executeRaw`INSERT INTO public.rag_document_search(tenant_id,document_id,index_version,content_state,source_text,source_revision)
    VALUES(${input.tenantId}::uuid,${input.documentId}::uuid,${RAG_SEARCH_VERSION},${input.content.state},${input.content.text},${input.revision})`;
  const entries=JSON.stringify(searchPassages(input.fileName,input.content.text).map((text,index)=>({text,index})));
  await tx.$executeRaw`INSERT INTO public.rag_document_search_passages(tenant_id,document_id,passage_index,search_text)
    SELECT ${input.tenantId}::uuid,${input.documentId}::uuid,p.index,p.text
    FROM jsonb_to_recordset(${entries}::jsonb) AS p(index integer,text text)`;
}

export async function saveRagSearchContent(input:{tenantId:string;userId:string;document:SearchDocument;revision:string;content:SearchContent;reprocess?:boolean}):Promise<boolean> {
  return prisma.$transaction(async tx=>{
    await setTenantContext(tx,input.tenantId,input.userId);
    // Serializes extraction commits and prevents deleted/replaced sources being resurrected.
    const parent=await tx.$queryRaw<Array<{document_id:string}>>`SELECT document_id FROM public.rag_documents_metadata
      WHERE tenant_id=${input.tenantId}::uuid AND document_id=${input.document.document_id}::uuid FOR UPDATE`;
    if (!parent.length) return false;
    const current=await tx.rag_documents_metadata.findFirst({where:{tenant_id:input.tenantId,document_id:input.document.document_id},select:searchDocumentSelect});
    if (!current || searchRevision(current)!==input.revision) return false;
    if(input.reprocess && current.storage_bucket_path.startsWith('ceopro-db://') && input.content.state==='ready'){
      await tx.rag_documents_metadata.update({where:{document_id:current.document_id},data:{processed_status:'Stored'}});
      current.processed_status='Stored';
    }
    await replaceSearchContent(tx,{tenantId:input.tenantId,documentId:current.document_id,fileName:current.file_name,content:input.content,revision:searchRevision(current)});
    return true;
  });
}
export async function getRagDocumentForReindex(input:{tenantId:string;userId:string;documentId:string}){
 return prisma.$transaction(async tx=>{await setTenantContext(tx,input.tenantId,input.userId);
  return tx.rag_documents_metadata.findFirst({where:{tenant_id:input.tenantId,document_id:input.documentId,storage_bucket_path:{startsWith:'ceopro-db://'}},select:searchDocumentSelect});
 });
}

export async function getRagChunk(input: {
  tenantId: string;
  userId: string;
  chunkId: string;
}) {
  return prisma.$transaction(async (tx) => {
    await setTenantContext(tx, input.tenantId, input.userId);
    return tx.rag_document_chunks.findFirst({
      where: {
        tenant_id: input.tenantId,
        chunk_id: input.chunkId,
        rag_documents_metadata:{OR:[{storage_bucket_path:{not:{startsWith:"_generated/"}}},
          {storage_bucket_path:{startsWith:`_generated/${input.tenantId}/`}}]}
      },
      include: {
        rag_documents_metadata: {
          select: { file_name: true }
        }
      }
    });
  });
}

export async function saveUploadedRagDocument(input: {
  tenantId: string;
  userId: string;
  documentId: string;
  fileName: string;
  fileSizeBytes: number;
  contentType: string;
  sourceFileContent: Buffer;
  processedStatus: RagDocumentStatus;
  extractionUsageKb: number;
  searchContent?: SearchContent;
}) {
  return prisma.$transaction(async (tx) => {
    await setTenantContext(tx, input.tenantId, input.userId);
    await reserveFeatureUsageInTransaction(
      tx,
      input.tenantId,
      "document_extraction",
      input.extractionUsageKb
    );
    const document = await tx.rag_documents_metadata.create({
      data: {
        document_id: input.documentId,
        tenant_id: input.tenantId,
        file_name: input.fileName,
        storage_bucket_path: `ceopro-db://rag-documents/${input.documentId}`,
        file_size_bytes: BigInt(input.fileSizeBytes),
        content_type: input.contentType,
        uploaded_by_user_id: input.userId,
        source_file_content: new Uint8Array(input.sourceFileContent),
        processed_status: input.processedStatus
      }
    });
    if (input.searchContent) await replaceSearchContent(tx,{tenantId:input.tenantId,documentId:input.documentId,fileName:input.fileName,content:input.searchContent,revision:searchRevision({...document,rag_document_chunks:[]})});
    return document;
  });
}

export async function persistRagQuerySources(input: {
  tenantId: string;
  userId: string;
  sources: Array<{ documentId: string; text: string }>;
}, transaction?:Prisma.TransactionClient): Promise<Array<{ chunkId: string; documentId: string; text: string }>> {
  const run = async (tx:Prisma.TransactionClient) => {
    await setTenantContext(tx, input.tenantId, input.userId);
    const saved: Array<{ chunkId: string; documentId: string; text: string }> = [];

    for (const source of input.sources) {
      // pg_advisory_xact_lock returns PostgreSQL `void`. Execute it without
      // requesting result columns; Prisma's PostgreSQL adapter cannot decode
      // a `void` column returned by $queryRaw.
      await tx.$executeRaw`
        SELECT pg_advisory_xact_lock(hashtextextended(${source.documentId}, 0))
      `;
      const active=await tx.$queryRaw<Array<{document_id:string}>>`SELECT document_id FROM public.rag_documents_metadata
        WHERE tenant_id=${input.tenantId}::uuid AND document_id=${source.documentId}::uuid FOR KEY SHARE`;
      if (!active.length) throw new Error("A query source document was removed. Retry the query.");
      const existing = await tx.rag_document_chunks.findFirst({
        where: {
          tenant_id: input.tenantId,
          document_id: source.documentId,
          chunk_text_content: source.text
        },
        select: { chunk_id: true }
      });
      if (existing) {
        saved.push({
          chunkId: existing.chunk_id,
          documentId: source.documentId,
          text: source.text
        });
        continue;
      }

      const aggregate = await tx.rag_document_chunks.aggregate({
        where: {
          tenant_id: input.tenantId,
          document_id: source.documentId
        },
        _max: { chunk_index: true }
      });
      const created = await tx.rag_document_chunks.create({
        data: {
          tenant_id: input.tenantId,
          document_id: source.documentId,
          chunk_index: (aggregate._max.chunk_index ?? -1) + 1,
          chunk_text_content: source.text
        },
        select: { chunk_id: true }
      });
      saved.push({
        chunkId: created.chunk_id,
        documentId: source.documentId,
        text: source.text
      });
    }
    return saved;
  };
  return transaction ? run(transaction) : prisma.$transaction(run);
}

/** Read/delete never require spare extraction quota or an active storage plan. */
export async function deleteStoredRagDocument(input: {tenantId: string; userId: string; documentId: string}) {
  return prisma.$transaction(async tx => {
    await setTenantContext(tx,input.tenantId,input.userId);
    await tx.$executeRaw`SELECT pg_advisory_xact_lock(hashtextextended(${'document-storage:' + input.tenantId},0))`;
    const document=await tx.rag_documents_metadata.findFirst({where:{tenant_id:input.tenantId,document_id:input.documentId},select:{storage_bucket_path:true}});
    if(!document)return {status:"not_found" as const};
    if(!document.storage_bucket_path.startsWith("ceopro-db://")) return {status:"external" as const};
    // Composite FK cascades chunks. Bytes and metadata disappear in this transaction.
    const result=await tx.rag_documents_metadata.deleteMany({where:{tenant_id:input.tenantId,document_id:input.documentId}});
    return {status:result.count ? "deleted" as const : "not_found" as const};
  });
}

async function storageInTransaction(tx:Prisma.TransactionClient,tenantId:string) {
  const rows=await tx.$queryRaw<Array<{bytes:bigint}>>`SELECT public.retained_document_bytes(${tenantId}::uuid) AS bytes`;
  const {subscription,planFeature}=await getFeatureAccessInfo(tenantId,"document_storage_mb",tx);
  const usedBytes=Number(rows[0]?.bytes??0n);
  const included=Boolean(subscription && planFeature);
  const limitBytes=included && planFeature!.limit_value!==null ? planFeature!.limit_value*1048576 : null;
  return {usedBytes,limitBytes,included,isUnlimited:included && limitBytes===null,
    remainingBytes:included ? limitBytes===null ? null : Math.max(0,limitBytes-usedBytes) : 0,
    isOverLimit:limitBytes!==null && usedBytes>limitBytes,unit:"MiB",retrievalMode:"on_demand"};
}
export async function getRagStorage(input: {tenantId: string; userId: string}) {
  return prisma.$transaction(async tx => {
    await setTenantContext(tx,input.tenantId,input.userId);
    return storageInTransaction(tx,input.tenantId);
  });
}
export async function getRagDocumentPage(input:{tenantId:string;userId:string;page:number;pageSize:number;search?:string;type?:string;sort?:'newest'|'oldest'}) {
  return prisma.$transaction(async tx=>{
    await setTenantContext(tx,input.tenantId,input.userId);
    const where:Prisma.rag_documents_metadataWhereInput={tenant_id:input.tenantId,
      ...(input.search?{file_name:{contains:input.search,mode:'insensitive'}}:{}),
      ...(input.type&&input.type!=='all'?{content_type:input.type}:{})};
    const order=input.sort==='oldest'?'asc':'desc';
    const documents=await tx.rag_documents_metadata.findMany({where,
      orderBy:[{uploaded_at:order},{document_id:order}],skip:(input.page-1)*input.pageSize,take:input.pageSize,
      select:{document_id:true,file_name:true,file_size_bytes:true,storage_bucket_path:true,content_type:true,
        uploaded_by_user_id:true,uploaded_at:true,processed_status:true,
        search_index:{select:{content_state:true,index_version:true}}}});
    const total=await tx.rag_documents_metadata.count({where});
    return {documents,total,storage:await storageInTransaction(tx,input.tenantId)};
  },{isolationLevel:"RepeatableRead"});
}
