import assert from "node:assert/strict";
import test from "node:test";
import {
  BUSINESS_FILE_STAGING_BATCH_SIZE,
  writeStagingRowsInBatches
} from "../../src/modules/dataconnection/repo/staging-batches.js";

test("a 39,498-row sales import stages bounded inserts in original order", async () => {
  const input = Array.from({ length: 39_498 }, (_, index) => index);
  const written: number[] = [];
  const sizes: number[] = [];
  await writeStagingRowsInBatches(input, async (batch) => {
    sizes.push(batch.length);
    written.push(...batch);
  });

  assert.equal(sizes.length, 79);
  assert.equal(sizes.at(-1), 498);
  assert.ok(sizes.every((size) => size > 0 && size <= BUSINESS_FILE_STAGING_BATCH_SIZE));
  assert.deepEqual(written, input);
});

test("a failed staging insert stops later writes so the enclosing transaction can roll back", async () => {
  const attempted: number[] = [];
  await assert.rejects(
    writeStagingRowsInBatches(Array.from({ length: 1_500 }, (_, index) => index), async (batch) => {
      attempted.push(batch[0]!);
      if (batch[0] === BUSINESS_FILE_STAGING_BATCH_SIZE) throw new Error("database unavailable");
    }),
    /database unavailable/
  );
  assert.deepEqual(attempted, [0, BUSINESS_FILE_STAGING_BATCH_SIZE]);
});
