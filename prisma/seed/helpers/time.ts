export interface SeedClock {
  now: Date;
  ago(days: number): Date;
}

export function createSeedClock(now = new Date()): SeedClock {
  return {
    now,
    ago(days: number) {
      return new Date(now.getTime() - days * 86_400_000);
    }
  };
}
