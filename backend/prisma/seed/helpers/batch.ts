export async function inBatches<T>(
  items: T[],
  fn: (batch: T[]) => Promise<unknown>,
  batchSize = 400
): Promise<void> {
  for (let i = 0; i < items.length; i += batchSize) {
    await fn(items.slice(i, i + batchSize));
  }
}
