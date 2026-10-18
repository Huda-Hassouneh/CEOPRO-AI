import type { MpiSubjectType } from "../types/mpi.types.js";

export const MPI_MINIMUM_REVIEWS = 5;
export const MPI_SAMPLE_LIMIT = 100;

export class MpiSubjectError extends Error {
  constructor(readonly code: "INVALID_SUBJECT" | "SUBJECT_NOT_FOUND") {
    super(code === "SUBJECT_NOT_FOUND" ? "Subject not found" : "Invalid perception subject");
    this.name = "MpiSubjectError";
  }
}

export class MpiAccessError extends Error {
  constructor(readonly code: "SUBSCRIPTION_NOT_FOUND" | "FEATURE_NOT_INCLUDED") {
    super("Market Perception access is unavailable");
    this.name = "MpiAccessError";
  }
}

export function validateMpiSubject(input: { tenantId: string; subjectType: MpiSubjectType; subjectId?: string }) {
  if (!["BUSINESS", "PRODUCT", "COMPETITOR"].includes(input.subjectType) ||
      (input.subjectType !== "BUSINESS" && !input.subjectId) ||
      (input.subjectType === "BUSINESS" && input.subjectId && input.subjectId.toLowerCase() !== input.tenantId.toLowerCase())) {
    throw new MpiSubjectError("INVALID_SUBJECT");
  }
}

export function eligibleMpiReviews<T extends { review_id: string; review_text: string; review_date: Date; collection_method: string }>(
  records: T[], asOf: Date
) {
  const seen = new Set<string>();
  return records.filter((review) => {
    if (seen.has(review.review_id) || !review.review_text.trim() ||
        !Number.isFinite(review.review_date.getTime()) || review.review_date > asOf ||
        !["PUBLIC_API", "PUBLIC_FEED", "MANUAL"].includes(review.collection_method)) return false;
    seen.add(review.review_id);
    return true;
  }).slice(0, MPI_SAMPLE_LIMIT);
}

export type ProviderSample = number | {
  status: "OK" | "LOW_SAMPLE_SIZE" | "UNKNOWN";
  minimum_required?: number;
  review_count?: number;
  analyzed_count?: number;
  sufficient?: boolean;
};

export function mpiSampleDecision(sample: ProviderSample, count: number) {
  const minimum = Math.max(MPI_MINIMUM_REVIEWS, typeof sample === "object" ? sample.minimum_required ?? MPI_MINIMUM_REVIEWS : MPI_MINIMUM_REVIEWS);
  const status = count < minimum || (typeof sample === "object" && (sample.status === "LOW_SAMPLE_SIZE" || sample.sufficient === false))
    ? "LOW_SAMPLE_SIZE" as const
    : typeof sample === "object" && sample.status === "UNKNOWN"
      ? "UNKNOWN" as const : "OK" as const;
  return { status, minimum_required: minimum, observed: count };
}
