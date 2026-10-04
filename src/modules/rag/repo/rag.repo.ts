import { prisma } from "../../../config/database.js";
import type { RagDocumentStatus } from "../types/rag.types.js";

export async function listRagDocuments(input: {
  tenantId: string;
  page: number;
  pageSize: number;
}) {
  return prisma.rag_documents_metadata.findMany({
    where: { tenant_id: input.tenantId },
    orderBy: { uploaded_at: "desc" },
    skip: (input.page - 1) * input.pageSize,
    take: input.pageSize
  });
}

export async function countRagDocuments(tenantId: string) {
  return prisma.rag_documents_metadata.count({
    where: { tenant_id: tenantId }
  });
}

export async function getRagChunk(tenantId: string, chunkId: string) {
  return prisma.rag_document_chunks.findFirst({
    where: {
      tenant_id: tenantId,
      chunk_id: chunkId
    },
    include: {
      rag_documents_metadata: {
        select: { file_name: true }
      }
    }
  });
}

export async function saveUploadedRagDocument(input: {
  tenantId: string;
  userId: string;
  documentId: string;
  fileName: string;
  fileSizeBytes: number;
  contentType: string;
  processedStatus: RagDocumentStatus;
}) {
  const existing = await prisma.rag_documents_metadata.findFirst({
    where: {
      tenant_id: input.tenantId,
      document_id: input.documentId
    }
  });

  const storageReference = `ai-rag://documents/${input.documentId}`;

  if (existing) {
    return prisma.rag_documents_metadata.update({
      where: { document_id: existing.document_id },
      data: {
        file_name: input.fileName,
        storage_bucket_path: storageReference,
        file_size_bytes: BigInt(input.fileSizeBytes),
        content_type: input.contentType,
        uploaded_by_user_id: input.userId,
        processed_status: input.processedStatus
      }
    });
  }

  return prisma.rag_documents_metadata.create({
    data: {
      document_id: input.documentId,
      tenant_id: input.tenantId,
      file_name: input.fileName,
      storage_bucket_path: storageReference,
      file_size_bytes: BigInt(input.fileSizeBytes),
      content_type: input.contentType,
      uploaded_by_user_id: input.userId,
      processed_status: input.processedStatus
    }
  });
}
