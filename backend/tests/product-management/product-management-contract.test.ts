import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { productCreateSchema, productUpdateSchema, productListSchema } from "../../src/modules/products/types/products.validation.js";
import { productCapacity, requireProductCapacity } from "../../src/modules/products/repo/product-capacity.js";
import { productWriteAllowed } from "../../src/modules/products/service/products.permissions.js";
import { matchProduct } from "../../src/modules/dataconnection/service/business-product-matching.js";
const input = { name: { ar: "شاي", en: "" }, sku: null, price: "0", costPrice: null, currency: "JOD", brand: { en: "", ar: "" }, category: { en: "", ar: "" }, description: { en: "", ar: "" } };
test("strict product input preserves decimal strings and zero, supports Arabic-only names", () => {
  assert.equal(productCreateSchema.parse(input).price, "0");
  assert.equal(productCreateSchema.parse({ ...input, price: "99999999.9999", currency: "jod" }).currency, "JOD");
  for (const invalid of [{ tenant_id: "other" }, { name: { en: "", ar: "" } }, { price: 5 }, { price: "-1" }, { price: "1e4" }, { price: "0.00001" }, { price: "100000000" }, { sku: "bad sku" }, { currency: "ZZZ" }, { version: 8 }])
    assert.equal(productCreateSchema.safeParse({ ...input, ...invalid }).success, false);
  assert.equal(productUpdateSchema.safeParse({ expectedVersion: 1 }).success, false);
  assert.equal(productUpdateSchema.safeParse({ expectedVersion: 0, price: "1" }).success, false);
  assert.equal(productUpdateSchema.safeParse({ price: "1" }).success, false);
  assert.equal(productListSchema.safeParse({ page: "0" }).success, false);
  assert.equal(productListSchema.safeParse({ tenant_id: "other" }).success, false);
});
test("capacity distinguishes zero, unlimited, missing allocation, and rejects a full catalog", async () => {
  let row = { current_usage: 2000n, limit_value: 2000, is_unlimited: false, included: true };
  const tx: any = { $queryRaw: async (parts: TemplateStringsArray, tenant: string) => { assert.match(parts.join("?"), /product_capacity_for_tenant/); assert.equal(tenant, "tenant"); return [row]; } };
  assert.equal((await productCapacity(tx, "tenant")).remaining, 0);
  await assert.rejects(requireProductCapacity(tx, "tenant"), (e: any) => e.code === "PRODUCT_CAPACITY_EXCEEDED");
  row = { ...row, current_usage: 1999n }; assert.equal((await requireProductCapacity(tx, "tenant")).remaining, 1);
  row = { ...row, limit_value: null as any, is_unlimited: true }; assert.equal((await requireProductCapacity(tx, "tenant")).remaining, null);
  row = { ...row, included: false }; await assert.rejects(requireProductCapacity(tx, "tenant"));
});
test("write permission rechecks active tenant membership and explicit product permission", async () => {
  let member: any = { role: { permissions: { all: true } } };
  const tx: any = { tenantUser: { findFirst: async (args: any) => { assert.deepEqual(args.where, { tenantId: "tenant", userId: "user", removedAt: null, platformStatus: "active" }); return member; } } };
  assert.equal(await productWriteAllowed(tx, { tenantId: "tenant", userId: "user" }), true);
  for (const value of [null, { role: { permissions: { "products.write": false } } }, { role: { permissions: { "products.write": "true" } } }]) { member = value; assert.equal(await productWriteAllowed(tx, { tenantId: "tenant", userId: "user" }), false); }
});
test("renamed products remain matchable through retained import aliases", () => {
  const row: any = { sheet: "inventory", row: 2, productId: "", sku: "", productName: "Old name" };
  const product = { product_id: "one", product_name: { en: "New name" }, sku: null, currency: "JOD", metadata: { import_name_aliases: ["old name"] } };
  assert.equal(matchProduct(row, [product]).productId, "one");
  assert.equal(matchProduct(row, [product, { ...product, product_id: "two" }]).status, "ambiguous");
});
test("migration keeps history, tenant scope, active SKU uniqueness and common capacity guard", () => {
  const sql = readFileSync(new URL("../../prisma/migrations/20261013160000_product_management_integrity/migration.sql", import.meta.url), "utf8");
  assert.match(sql, /lower\(btrim\(sku\)\)/); assert.match(sql, /WHERE deleted_at IS NULL/);
  assert.match(sql, /products-capacity:/); assert.match(sql, /FOR SHARE/);
  assert.match(sql, /NEW\.tenant_id IS DISTINCT FROM OLD\.tenant_id/);
  assert.match(sql, /AFTER INSERT OR UPDATE OF current_price, currency/);
  assert.match(sql, /OLD\.currency, NEW\.currency/);
  assert.doesNotMatch(sql, /DELETE FROM|UPDATE (?:public\.)?transactions/);
});
