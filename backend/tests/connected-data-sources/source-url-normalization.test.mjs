import assert from "node:assert/strict";
import test from "node:test";
import { normalizeSourceUrl } from "../../src/modules/dataconnection/types/source-url.ts";

test("website source URLs normalize host case, default ports, fragments, and trailing slashes", () => {
  assert.deepEqual(normalizeSourceUrl(" HTTPS://SHOP.EXAMPLE.COM:443/ "), {
    success: true,
    data: "https://shop.example.com"
  });
  assert.deepEqual(normalizeSourceUrl("https://shop.example.com/catalog///#top"), {
    success: true,
    data: "https://shop.example.com/catalog"
  });
});

test("website source URL can be omitted for providers that do not use one", () => {
  assert.deepEqual(normalizeSourceUrl(undefined), {
    success: true,
    data: undefined
  });
});

test("website source URLs reject unsupported protocols, credentials, local hosts, and IP literals", () => {
  for (const value of [
    "ftp://shop.example.com",
    "https://user:password@shop.example.com",
    "http://localhost:3000",
    "https://internal.example.local",
    "http://127.0.0.1",
    "https://[::1]"
  ]) {
    assert.equal(normalizeSourceUrl(value).success, false, value);
  }
});

test("website source URLs enforce the maximum length and type", () => {
  assert.equal(normalizeSourceUrl("https://shop.example.com/" + "a".repeat(2049)).success, false);
  assert.equal(normalizeSourceUrl(42).success, false);
});
