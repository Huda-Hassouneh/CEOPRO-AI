import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";

export function readProjectFile(relativePath: string): string {
  return fs.readFileSync(path.resolve(process.cwd(), relativePath), "utf8");
}

export function assertIncludesAll(
  source: string,
  needles: string[],
  label = "source",
): void {
  for (const needle of needles) {
    assert.ok(
      source.includes(needle),
      `${label} is missing required contract fragment: ${needle}`,
    );
  }
}

export function assertMatches(
  source: string,
  pattern: RegExp,
  message: string,
): void {
  assert.match(source, pattern, message);
}

export const UUID_A = "11111111-1111-4111-8111-111111111111";
export const UUID_B = "22222222-2222-4222-8222-222222222222";
