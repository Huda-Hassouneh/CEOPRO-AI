import { useCallback, useRef } from 'react';

// A synchronous in-flight lock for actions that create something server-side.
//
// Guarding a submit handler on react-query's `mutation.isPending` (or any
// other state that only updates on the next render) is not enough: both
// clicks of a fast double-click are dispatched before that state flips, so
// both pass the guard and the action runs twice - reproduced live as a
// duplicate product from one double-clicked "Create product". A ref is
// updated synchronously, so the second call is rejected immediately.
//
// Usage: const runLocked = useSubmitLock();
//        runLocked(() => mutation.mutateAsync(payload));
// The lock is released when the returned promise settles, success or
// failure, so a failed attempt can be retried.
export function useSubmitLock() {
  const lockedRef = useRef(false);
  return useCallback(async (action) => {
    if (lockedRef.current) return undefined;
    lockedRef.current = true;
    try {
      return await action();
    } finally {
      lockedRef.current = false;
    }
  }, []);
}
