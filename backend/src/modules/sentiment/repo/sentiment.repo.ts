import { prisma } from "../../../config/database.js";
import type { Prisma } from "../../../generated/prisma/client.js";
import type { SentimentSubjectType } from "../types/sentiment.types.js";

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

export async function getPendingReviews(input: {
  tenantId: string;
  userId: string;
  limit: number;
}) {
  return prisma.$transaction(async (tx) => {
    await setTenantContext(tx, input.tenantId, input.userId);
    return tx.reviews.findMany({
      where: {
        tenant_id: input.tenantId,
        source_status: "ALLOWED",
        safety_status: "SAFE",
        review_text: { not: "" },
        sentiment_results: { is: null }
      },
      select: { review_id: true, review_text: true },
      orderBy: [{ review_date: "asc" }, { review_id: "asc" }],
      take: input.limit
    });
  });
}

export async function saveSentimentResults(input: {
  tenantId: string;
  userId: string;
  results: Array<{
    reviewId: string;
    score: number;
    label: "positive" | "neutral" | "negative";
    positiveProbability: number;
    neutralProbability: number;
    negativeProbability: number;
    confidence: number;
    modelVersion: string;
  }>;
}): Promise<void> {
  await prisma.$transaction(async (tx) => {
    await setTenantContext(tx, input.tenantId, input.userId);
    for (const result of input.results) {
      await tx.sentiment_results.upsert({
        where: { review_id: result.reviewId },
        create: {
          tenant_id: input.tenantId,
          review_id: result.reviewId,
          sentiment_score: result.score,
          sentiment_label: result.label,
          positive_probability: result.positiveProbability,
          neutral_probability: result.neutralProbability,
          negative_probability: result.negativeProbability,
          confidence: result.confidence,
          model_version: result.modelVersion
        },
        update: {
          sentiment_score: result.score,
          sentiment_label: result.label,
          positive_probability: result.positiveProbability,
          neutral_probability: result.neutralProbability,
          negative_probability: result.negativeProbability,
          confidence: result.confidence,
          model_version: result.modelVersion,
          processed_at: new Date()
        }
      });
    }
  });
}

export async function getSentimentAggregate(input: {
  tenantId: string;
  userId: string;
  subjectType: SentimentSubjectType;
  subjectId?: string;
}) {
  return prisma.$transaction(async (tx) => {
    await setTenantContext(tx, input.tenantId, input.userId);

    const reviewWhere: Prisma.reviewsWhereInput = {
      tenant_id: input.tenantId,
      source_status: "ALLOWED",
      safety_status: "SAFE"
    };
    if (input.subjectType !== "BUSINESS") {
      reviewWhere.subject_type = input.subjectType;
      if (input.subjectType === "PRODUCT" && input.subjectId) {
        reviewWhere.product_id = input.subjectId;
      }
      if (input.subjectType === "COMPETITOR" && input.subjectId) {
        reviewWhere.competitor_id = input.subjectId;
      }
    }

    const rows = await tx.sentiment_results.findMany({
      where: {
        tenant_id: input.tenantId,
        reviews: { is: reviewWhere }
      },
      select: { sentiment_score: true, sentiment_label: true }
    });

    const labelCounts = { positive: 0, neutral: 0, negative: 0 };
    let scoreTotal = 0;
    for (const row of rows) {
      if (row.sentiment_label in labelCounts) {
        labelCounts[row.sentiment_label as keyof typeof labelCounts] += 1;
      }
      scoreTotal += Number(row.sentiment_score);
    }

    return {
      count: rows.length,
      averageScore: rows.length > 0 ? scoreTotal / rows.length : null,
      labelCounts
    };
  });
}
