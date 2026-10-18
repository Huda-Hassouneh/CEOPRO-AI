const statuses = new Set(["OK", "NO_ELIGIBLE_REVIEWS", "INSUFFICIENT_REVIEWS", "MODEL_UNAVAILABLE", "SERVICE_UNAVAILABLE", "SUBJECT_UNAVAILABLE", "NOT_INCLUDED", "NOT_ANALYZED"]);

export function perceptionPresentation(summary, fallbackStatus = "NOT_ANALYZED") {
  const supported = summary?.status === "OK" && summary.sample_size?.status === "OK" &&
    typeof summary.mpi === "number" && Number.isFinite(summary.mpi) && summary.mpi >= 0 && summary.mpi <= 100;
  const requestedStatus = supported ? "OK" : summary?.reason ?? (fallbackStatus === "OK" || summary?.status === "OK" ? "MODEL_UNAVAILABLE" : fallbackStatus);
  const status = statuses.has(requestedStatus) ? requestedStatus : "MODEL_UNAVAILABLE";
  const labels = summary?.label_counts ?? null;
  const ordered = labels ? Object.entries(labels).filter(([label, count]) =>
    ["positive", "neutral", "negative"].includes(label) && Number.isFinite(count)) : [];
  const max = ordered.length ? Math.max(...ordered.map(([, count]) => count)) : 0;
  const winners = ordered.filter(([, count]) => count === max);
  return {
    status, supported, score: supported ? summary.mpi : null,
    dominantLabel: supported && max > 0 && winners.length === 1 ? winners[0][0] : null,
    reviewCount: summary?.review_count ?? null,
    minimum: summary?.sample_size?.minimum_required ?? null,
    labels: summary?.analysis_performed ? labels : null,
    confidence: supported && typeof summary.confidence_score === "number" && Number.isFinite(summary.confidence_score) && summary.confidence_score >= 0 && summary.confidence_score <= 1 ? summary.confidence_score : null,
    evidence: summary?.evidence ?? null,
    asOf: summary?.as_of ?? null
  };
}
