function getApiError(error) {
  const backendError = error?.response?.data?.error;

  return {
    status: error?.response?.status ?? backendError?.statusCode ?? null,

    code: backendError?.code ?? error?.code ?? null,

    details: backendError?.details ?? error?.details ?? null
  };
}

function getDetailMessage(details) {
  if (typeof details === "string") {
    return details;
  }

  if (
    details &&
    typeof details === "object" &&
    typeof details.message === "string"
  ) {
    return details.message;
  }

  return "";
}

function formatAmount(value, unit, locale) {
  let numeric = Number(value);

  if (!Number.isFinite(numeric)) {
    return null;
  }

  let normalizedUnit = String(unit || "").toUpperCase();

  if (normalizedUnit === "KB" && numeric >= 1024) {
    numeric /= 1024;
    normalizedUnit = "MB";
  }

  if (normalizedUnit === "MB" && numeric >= 1024) {
    numeric /= 1024;
    normalizedUnit = "GB";
  }

  const formatted = new Intl.NumberFormat(locale, {
    maximumFractionDigits: numeric < 10 ? 2 : 1
  }).format(numeric);

  return normalizedUnit ? `${formatted} ${normalizedUnit}` : formatted;
}

function createFeedback(variant, message) {
  return {
    variant,
    message
  };
}

export function getRagErrorFeedback(
  error,
  { action = "generic", t, locale = "en" } = {}
) {
  const { status, code, details } = getApiError(error);

  const detailMessage = getDetailMessage(details);
  const detailLower = detailMessage.toLowerCase();

  /*
   * CLIENT + SERVER FILE VALIDATION
   */
  if (code === "FILE_SIZE_LIMIT_EXCEEDED" || status === 413) {
    return createFeedback("warning", t("ragAssistant.errors.fileTooLarge"));
  }

  if (code === "INVALID_FILE_UPLOAD") {
    return createFeedback("warning", t("ragAssistant.errors.invalidFile"));
  }

  /*
   * QUOTA / CAPACITY
   */
  if (code === "PAYMENT_REQUIRED" || status === 402) {
    if (action === "chat") {
      return createFeedback(
        "warning",
        t("ragAssistant.errors.ragQuotaReached")
      );
    }

    if (action === "upload") {
      const isStorage =
        details?.reason === "CAPACITY_REACHED" ||
        details?.feature_code === "document_storage_mb";

      const requested = formatAmount(details?.requested, details?.unit, locale);

      const remaining = formatAmount(details?.remaining, details?.unit, locale);

      if (isStorage) {
        if (requested && remaining) {
          return createFeedback(
            "warning",
            t("ragAssistant.errors.storageQuotaDetailed", {
              requested,
              remaining
            })
          );
        }

        return createFeedback("warning", t("ragAssistant.errors.storageQuota"));
      }

      if (requested && remaining) {
        return createFeedback(
          "warning",
          t("ragAssistant.errors.extractionQuotaDetailed", {
            requested,
            remaining
          })
        );
      }

      return createFeedback(
        "warning",
        t("ragAssistant.errors.extractionQuota")
      );
    }
  }

  /*
   * FEATURE / PERMISSION
   */
  if (
    code === "FORBIDDEN" ||
    code === "INSUFFICIENT_PERMISSIONS" ||
    code === "TENANT_ACCESS_DENIED" ||
    status === 403
  ) {
    if (action === "chat") {
      return createFeedback("warning", t("ragAssistant.errors.ragNotIncluded"));
    }

    if (action === "upload") {
      if (detailLower.includes("storage")) {
        return createFeedback(
          "warning",
          t("ragAssistant.errors.storageNotIncluded")
        );
      }

      if (detailLower.includes("extraction")) {
        return createFeedback(
          "warning",
          t("ragAssistant.errors.extractionNotIncluded")
        );
      }

      return createFeedback(
        "warning",
        t("ragAssistant.errors.uploadNotAllowed")
      );
    }

    return createFeedback("warning", t("ragAssistant.errors.notAllowed"));
  }

  /*
   * AUTHENTICATION
   */
  if (
    [
      "UNAUTHORIZED",
      "INVALID_TOKEN",
      "TOKEN_EXPIRED",
      "INVALID_AUTH_HEADER"
    ].includes(code) ||
    status === 401
  ) {
    return createFeedback("warning", t("ragAssistant.errors.sessionExpired"));
  }

  /*
   * RAG REQUEST VALIDATION
   */
  if (
    [
      "INVALID_REQUEST",
      "INVALID_PARAMETER",
      "VALIDATION_ERROR",
      "MALFORMED_HISTORY_JSON"
    ].includes(code)
  ) {
    return createFeedback(
      "warning",
      action === "chat"
        ? t("ragAssistant.errors.invalidQuestion")
        : t("ragAssistant.errors.invalidRequest")
    );
  }

  /*
   * AI SERVICE
   */
  if (code === "UPSTREAM_LLM_FAILURE") {
    return createFeedback("error", t("ragAssistant.errors.aiUnavailable"));
  }

  if (
    code === "EXTERNAL_SERVICE_ERROR" ||
    code === "SERVICE_UNAVAILABLE" ||
    status === 502 ||
    status === 503
  ) {
    return createFeedback("error", t("ragAssistant.errors.serviceUnavailable"));
  }

  /*
   * NOT FOUND
   */
  if (code === "RESOURCE_NOT_FOUND" || status === 404) {
    return createFeedback("warning", t("ragAssistant.errors.resourceNotFound"));
  }

  /*
   * RATE LIMIT
   */
  if (status === 429) {
    return createFeedback("warning", t("ragAssistant.errors.tooManyRequests"));
  }

  /*
   * SERVER
   */
  if (code === "INTERNAL_SERVER_ERROR" || (status && status >= 500)) {
    return createFeedback("error", t("ragAssistant.errors.serverError"));
  }

  /*
   * NETWORK ERROR
   *
   * Axios has no response when the API itself
   * could not be reached.
   */
  if (!error?.response) {
    return createFeedback("error", t("ragAssistant.errors.network"));
  }

  /*
   * FINAL CONTEXT-SPECIFIC FALLBACK
   */
  const fallbackKey =
    action === "upload"
      ? "ragAssistant.errors.uploadUnknown"
      : action === "chat"
        ? "ragAssistant.errors.chatUnknown"
        : action === "documents"
          ? "ragAssistant.errors.documentsUnknown"
          : "ragAssistant.errors.unknown";

  return createFeedback("error", t(fallbackKey));
}
