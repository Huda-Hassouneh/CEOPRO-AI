import { prisma } from "../../../config/database.js";
import type { Prisma } from "../../../generated/prisma/client.js";
import type { RagDocumentStatus } from "../types/rag.types.js";

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
}) {
  return prisma.$transaction(async (tx) => {
    await setTenantContext(tx, input.tenantId, input.userId);
    return tx.rag_documents_metadata.findMany({
      where: {
        tenant_id: input.tenantId,
        processed_status: "Processed"
      },
      orderBy: [{ uploaded_at: "desc" }, { document_id: "desc" }],
      take: input.limit,
      select: {
        document_id: true,
        file_name: true,
        content_type: true,
        source_file_content: true,
        rag_document_chunks: {
          orderBy: { chunk_index: "asc" },
          select: { chunk_text_content: true }
        }
      }
    });
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
        chunk_id: input.chunkId
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
}) {
  return prisma.$transaction(async (tx) => {
    await setTenantContext(tx, input.tenantId, input.userId);
    return tx.rag_documents_metadata.create({
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
  });
}

export async function persistRagQuerySources(input: {
  tenantId: string;
  userId: string;
  sources: Array<{ documentId: string; text: string }>;
}): Promise<Array<{ chunkId: string; documentId: string; text: string }>> {
  return prisma.$transaction(async (tx) => {
    await setTenantContext(tx, input.tenantId, input.userId);
    const saved: Array<{ chunkId: string; documentId: string; text: string }> = [];

    for (const source of input.sources) {
      // pg_advisory_xact_lock returns PostgreSQL `void`. Execute it without
      // requesting result columns; Prisma's PostgreSQL adapter cannot decode
      // a `void` column returned by $queryRaw.
      await tx.$executeRaw`
        SELECT pg_advisory_xact_lock(hashtextextended(${source.documentId}, 0))
      `;
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
  });
}
