import { useCallback, useState } from "react";
import { billingApi, getApiError } from "../api/billingApi.js";

const getSafeRecoveryUrl = (value) => {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error("Subscription recovery URL is unavailable.");
  }

  const url = new URL(value, window.location.origin);
  if (url.protocol !== "https:" && url.protocol !== "http:") {
    throw new Error("Subscription recovery URL is invalid.");
  }

  return url.toString();
};

export function useSubscriptionRecovery() {
  const [isRecovering, setIsRecovering] = useState(false);
  const [error, setError] = useState(null);

  const recover = useCallback(async () => {
    setIsRecovering(true);
    setError(null);

    try {
      const response = await billingApi.createSubscriptionRecovery();
      const recovery = response?.data ?? response;
      const recoveryUrl = getSafeRecoveryUrl(recovery?.url);

      window.location.assign(recoveryUrl);
      return recovery;
    } catch (requestError) {
      const apiError = getApiError(requestError);
      setError(apiError);
      return null;
    } finally {
      setIsRecovering(false);
    }
  }, []);

  const clearError = useCallback(() => setError(null), []);

  return {
    recover,
    isRecovering,
    error,
    clearError
  };
}
