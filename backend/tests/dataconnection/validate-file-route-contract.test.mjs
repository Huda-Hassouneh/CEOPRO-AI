import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("Data Connection upload validates file content before calling its controller", async () => {
  const route = await read("../../src/modules/dataconnection/route/dataconnection.route.ts");
  assert.match(
    route,
    /upload\.single\("file"\),\s*validateFile,\s*dataConnectionController\.uploadFile/
  );
});

test("compatibility extraction upload uses the same file validation", async () => {
  const route = await read("../../src/modules/features/route/features.route.ts");
  assert.match(
    route,
    /upload\.single\("file"\),\s*validateFile,\s*extractionController\.uploadFile/
  );
});
