import { prisma } from "../../../config/database.js";
import type { Prisma } from "../../../generated/prisma/client.js";
import type { MpiEvidence, MpiSubjectType } from "../types/mpi.types.js";
import { eligibleMpiReviews, MPI_SAMPLE_LIMIT, MpiSubjectError, validateMpiSubject } from "../service/mpi.policy.js";

async function setTenantContext(tx: Prisma.TransactionClient, tenantId: string, userId: string) {
  await tx.$queryRaw`
    SELECT set_config('app.current_tenant_id', ${tenantId}, true),
           set_config('app.current_user_id', ${userId}, true)
  `;
}

export async function getReviewsForMpi(input: {
  tenantId: string; userId: string; subjectType: MpiSubjectType; subjectId?: string; asOf: Date;
}) {
  validateMpiSubject(input);
  return prisma.$transaction(async (tx) => {
    await setTenantContext(tx, input.tenantId, input.userId);
    const company = await tx.company.findFirst({
      where: { id: input.tenantId, deletedAt: null }, select: { countryCode: true }
    });
    if (!company) throw new MpiSubjectError("SUBJECT_NOT_FOUND");
    if (input.subjectType === "PRODUCT") {
      const product = await tx.products.findFirst({
        where: { tenant_id: input.tenantId, product_id: input.subjectId!, deleted_at: null },
        select: { product_id: true }
      });
      if (!product) throw new MpiSubjectError("SUBJECT_NOT_FOUND");
    }
    if (input.subjectType === "COMPETITOR") {
      const competitor = await tx.tenant_competitors.findFirst({
        where: { tenant_id: input.tenantId, global_competitor_id: input.subjectId!, is_tracked: true },
        select: { global_competitor_id: true }
      });
      if (!competitor) throw new MpiSubjectError("SUBJECT_NOT_FOUND");
    }
    const where: Prisma.reviewsWhereInput = {
      tenant_id: input.tenantId,
      subject_type: input.subjectType,
      source_status: "ALLOWED",
      safety_status: "SAFE",
      review_text: { not: "" },
      review_date: { lte: input.asOf },
      collection_method: { in: ["PUBLIC_API", "PUBLIC_FEED", "MANUAL"] },
      ...(input.subjectType === "BUSINESS" ? { product_id: null, competitor_id: null } :
        input.subjectType === "PRODUCT" ? { product_id: input.subjectId, competitor_id: null } :
        { competitor_id: input.subjectId })
    };
    // Paginate over unusable text, retaining the newest 100 genuinely eligible reviews.
    const reviews: Array<{ review_id: string; review_text: string; review_date: Date; collection_method: string }> = [];
    let cursor: string | undefined;
    while (reviews.length < MPI_SAMPLE_LIMIT) {
      const batch = await tx.reviews.findMany({
        where,
        select: { review_id: true, review_text: true, review_date: true, collection_method: true },
        orderBy: [{ review_date: "desc" }, { review_id: "desc" }],
        take: MPI_SAMPLE_LIMIT,
        ...(cursor ? { cursor: { review_id: cursor }, skip: 1 } : {})
      });
      reviews.push(...eligibleMpiReviews(batch, input.asOf).slice(0, MPI_SAMPLE_LIMIT - reviews.length));
      if (batch.length < MPI_SAMPLE_LIMIT) break;
      const nextCursor = batch[batch.length - 1]!.review_id;
      if (nextCursor === cursor) break;
      cursor = nextCursor;
    }
    return { reviews, countryCode: company.countryCode };
  }, { isolationLevel: "RepeatableRead", timeout: 15_000 });
}

export async function persistMpiEvidence(input: {
  tenantId: string; userId: string; subjectType: MpiSubjectType; subjectId?: string;
  status: "OK" | "UNKNOWN"; reason: string | null; mpi: number | null;
  reviewCount: number; weightedSentimentScore: number | null; volumeConfidence: number | null;
  explanationText: string | null; confidenceScore: number | null;
  evidence: MpiEvidence; asOf: string; sampleSize: Prisma.InputJsonObject;
  labelCounts: Prisma.InputJsonObject | null;
}) {
  return prisma.$transaction(async (tx) => {
    await setTenantContext(tx, input.tenantId, input.userId);
    const evidence = await tx.evidence_records.create({
      data: {
        tenant_id: input.tenantId, source_module: "market-intelligence", metric_name: "market_perception_index",
        category: input.status === "OK" ? "FACT" : "UNKNOWN",
        metric_value_json: {
          subject_type: input.subjectType, subject_id: input.subjectId ?? null,
          status: input.status, reason: input.reason, mpi: input.mpi, review_count: input.reviewCount,
          weighted_sentiment_score: input.weightedSentimentScore, volume_confidence: input.volumeConfidence,
          sample_size: input.sampleSize, label_counts: input.labelCounts,
          as_of: input.asOf, observation_period: input.evidence.observation_period,
          eligible_review_count: input.evidence.eligible_review_count,
          sentiment_model: input.evidence.sentiment_model, model_revision: input.evidence.model_revision
        },
        source_record_ids: {
          subject_type: input.subjectType, subject_id: input.subjectId ?? null,
          review_ids: input.evidence.source_review_ids, review_id_scope: "submitted_sample",
          collection_methods: input.evidence.collection_methods, sample_limit: input.evidence.sample_limit
        },
        confidence_score: input.confidenceScore,
        explanation_text: input.explanationText?.trim() || (
          input.status === "OK"
            ? "The market-intelligence service returned an analysis without an explanation."
            : "The market-intelligence service returned UNKNOWN without an explanation."
        )
      }, select: { evidence_id: true }
    });
    return evidence.evidence_id;
  });
}
