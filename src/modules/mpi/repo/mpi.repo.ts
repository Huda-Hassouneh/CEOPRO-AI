import { prisma } from "../../../config/database.js";
import type { Prisma } from "../../../generated/prisma/client.js";
import type { MpiSubjectType } from "../types/mpi.types.js";

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

export async function getReviewsForMpi(input: {
  tenantId: string;
  userId: string;
  subjectType: MpiSubjectType;
  subjectId?: string;
}) {
  return prisma.$transaction(async (tx) => {
    await setTenantContext(tx, input.tenantId, input.userId);
    const where: Prisma.reviewsWhereInput = {
      tenant_id: input.tenantId,
      source_status: "ALLOWED",
      safety_status: "SAFE",
      review_text: { not: "" },
      collection_method: { in: ["PUBLIC_API", "PUBLIC_FEED", "MANUAL"] }
    };

    if (input.subjectType !== "BUSINESS") {
      where.subject_type = input.subjectType;
      if (input.subjectType === "PRODUCT" && input.subjectId) {
        where.product_id = input.subjectId;
      }
      if (input.subjectType === "COMPETITOR" && input.subjectId) {
        where.competitor_id = input.subjectId;
      }
    }

    return tx.reviews.findMany({
      where,
      select: {
        review_id: true,
        review_text: true,
        review_date: true,
        collection_method: true
      },
      orderBy: [{ review_date: "desc" }, { review_id: "desc" }],
      take: 100
    });
  });
}

export async function persistMpiEvidence(input: {
  tenantId: string;
  userId: string;
  subjectType: MpiSubjectType;
  subjectId?: string;
  status: "OK" | "UNKNOWN";
  mpi: number | null;
  reviewCount: number;
  weightedSentimentScore: number;
  volumeConfidence: number;
  explanationText: string;
  confidenceScore: number;
}): Promise<string> {
  return prisma.$transaction(async (tx) => {
    await setTenantContext(tx, input.tenantId, input.userId);
    const evidence = await tx.evidence_records.create({
      data: {
        tenant_id: input.tenantId,
        source_module: "market-intelligence",
        metric_name: "market_perception_index",
        metric_value_json: {
          subject_type: input.subjectType,
          subject_id: input.subjectId ?? null,
          status: input.status,
          mpi: input.mpi,
          review_count: input.reviewCount,
          weighted_sentiment_score: input.weightedSentimentScore,
          volume_confidence: input.volumeConfidence
        },
        source_record_ids: {
          subject_type: input.subjectType,
          subject_id: input.subjectId ?? null
        },
        confidence_score: input.confidenceScore,
        explanation_text: input.explanationText
      },
      select: { evidence_id: true }
    });
    return evidence.evidence_id;
  });
}
