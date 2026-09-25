import { useCallback, useEffect, useRef, useState } from 'react';
import { billingApi, getApiError } from '../api/billingApi.js';

const isNotFound = (error) => {
  const apiError = getApiError(error);
  return apiError.status === 404 || apiError.code === 'SUBSCRIPTION_NOT_FOUND';
};

export function useSubscriptionConfirmation({ attempts = 6, intervalMs = 1500 } = {}) {
  const [state, setState] = useState({ status: 'checking', subscription: null, error: null });
  const runId = useRef(0);

  const check = useCallback(async () => {
    const currentRun = ++runId.current;
    setState((current) => ({ ...current, status: 'checking', error: null }));

    for (let attempt = 0; attempt < attempts; attempt += 1) {
      try {
        const response = await billingApi.getSubscription();
        if (currentRun !== runId.current) return;
        const subscription = response?.data ?? null;
        if (subscription) {
          setState({ status: 'confirmed', subscription, error: null });
          return;
        }
      } catch (error) {
        if (currentRun !== runId.current) return;
        if (!isNotFound(error)) {
          setState({ status: 'error', subscription: null, error: getApiError(error) });
          return;
        }
      }

      if (attempt < attempts - 1) {
        await new Promise((resolve) => setTimeout(resolve, intervalMs));
        if (currentRun !== runId.current) return;
      }
    }

    if (currentRun === runId.current) {
      setState({ status: 'pending', subscription: null, error: null });
    }
  }, [attempts, intervalMs]);

  useEffect(() => {
    check();
    return () => {
      runId.current += 1;
    };
  }, [check]);

  return {
    ...state,
    retry: check,
    isChecking: state.status === 'checking',
  };
}
