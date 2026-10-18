import assert from "node:assert/strict";
import test from "node:test";
import { matchProduct, matchImportProducts } from "../../src/modules/dataconnection/service/business-product-matching.js";
import { parseStructuredBusinessFile } from "../../src/modules/dataconnection/service/structured-business-import.js";

const id = "123e4567-e89b-42d3-a456-426614174000";
const id2 = "123e4567-e89b-42d3-a456-426614174001";
const products = [
  { product_id: id, sku: "ROSE-01", product_name: { en: "Red Roses", ar: "ورود حمراء" }, currency: "JOD" },
  { product_id: id2, sku: null, product_name: { en: "Red Roses" }, currency: "JOD" }
];
const file = (text: string) => ({ originalname: "stock.csv", size: Buffer.byteLength(text), buffer: Buffer.from(text) });
const header = "product_name,sku,stock_quantity,reorder_level,safety_stock,warehouse_location";

test("name-only templates parse and matched SKU disambiguates a duplicate name", () => {
  const parsed = parseStructuredBusinessFile("inventory", file(`${header}\nRed Roses,ROSE-01,10,2,1,Main\n`));
  const matches = matchImportProducts(parsed, products);
  assert.equal(matches[0]?.status, "matched");
  assert.equal(matches[0]?.productId, id);
  assert.equal(matches[0]?.row, 2);
});

test("ambiguous and missing names are never guessed; multilingual exact names match", () => {
  const parsed = parseStructuredBusinessFile("inventory", file(`${header}\nRed Roses,,10,2,1,Main\nورود حمراء,,9,2,1,Main\nUnknown,,1,1,0,Main\n`));
  const matches = matchImportProducts(parsed, products);
  assert.deepEqual(matches.map((row) => row.status), ["ambiguous", "matched", "missing"]);
  assert.equal(matches[0]?.candidates.length, 2);
  assert.equal(matches[1]?.productId, id);
});

test("provided ID and name or SKU disagreement is a blocking conflict", () => {
  const parsed = parseStructuredBusinessFile("inventory", file(`product_id,product_name,sku,stock_quantity,reorder_level,safety_stock\n${id},Red Roses,OTHER,1,0,0\n`));
  assert.equal(matchImportProducts(parsed, products)[0]?.status, "conflict");
  const legacy = parseStructuredBusinessFile("inventory", file(`product_id,stock_quantity,reorder_level,safety_stock\n${id},1,0,0\n`));
  assert.equal(matchImportProducts(legacy, products)[0]?.status, "matched");
  assert.equal(matchProduct(legacy.inventory[0]!, []).status, "missing");
});
