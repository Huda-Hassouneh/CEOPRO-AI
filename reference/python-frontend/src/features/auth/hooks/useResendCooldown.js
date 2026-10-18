import { useCallback, useEffect, useState } from 'react';

export function useResendCooldown(durationSeconds = 30) {
  const [remainingSeconds, setRemainingSeconds] = useState(0);

  useEffect(() => {
    if (remainingSeconds <= 0) return undefined;
    const timer = window.setTimeout(() => {
      setRemainingSeconds((current) => Math.max(0, current - 1));
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [remainingSeconds]);

  const startCooldown = useCallback(() => {
    setRemainingSeconds(durationSeconds);
  }, [durationSeconds]);

  return {
    isCoolingDown: remainingSeconds > 0,
    remainingSeconds,
    startCooldown,
  };
}
