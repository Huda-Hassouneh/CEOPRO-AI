import assert from "node:assert/strict";
import test from "node:test";
import { parseSalesStagingRow } from "../../src/modules/dataconnection/service/sales-staging-row.js";

test("maps a complete staged sales row for transaction persistence", () => {
  const result = parseSalesStagingRow({
    product_name: "Arabica Coffee Beans 500g",
    quantity: "8",
    unit_price: "2.62",
    amount_raw: "20.33",
    currency: "jod",
    transaction_date: "2025-01-14",
    discount_pct: "3",
    invoice_id: "INV-2026-0000002"
  });

  assert.equal(result.ok, true);
  if (!result.ok) return;
  assert.equal(result.value.productName, "Arabica Coffee Beans 500g");
  assert.equal(result.value.quantity, 8);
  assert.equal(result.value.unitPrice, "2.6200");
  assert.equal(result.value.totalPrice, "20.3300");
  assert.equal(result.value.currency, "JOD");
  assert.equal(result.value.transactionDate.toISOString(), "2025-01-14T00:00:00.000Z");
});

test("calculates discounted total exactly when amount_raw is absent", () => {
  const result = parseSalesStagingRow({
    product_name: "Coffee",
    quantity: "8",
    unit_price: "2.62",
    currency: "JOD",
    transaction_date: "2025-01-14",
    discount_pct: "3"
  });

  assert.equal(result.ok, true);
  if (result.ok) assert.equal(result.value.totalPrice, "20.3312");
});

test("rejects incomplete or unsafe business values instead of inserting them", () => {
  const missingCurrency = parseSalesStagingRow({
    product_name: "Micro USB Cable 1m",
    quantity: "2",
    unit_price: "1.5",
    transaction_date: "2025-01-01 15:34:00"
  });
  const invalidQuantity = parseSalesStagingRow({
    product_name: "Micro USB Cable 1m",
    quantity: "2.5",
    unit_price: "1.5",
    currency: "JOD",
    transaction_date: "2025-01-01"
  });
  const invalidDate = parseSalesStagingRow({
    product_name: "Micro USB Cable 1m",
    quantity: "2",
    unit_price: "1.5",
    currency: "JOD",
    transaction_date: "2025-02-30"
  });
  const overPrecision = parseSalesStagingRow({
    product_name: "Bulk Product",
    quantity: "999999999",
    unit_price: "99999999.9999",
    currency: "JOD",
    transaction_date: "2025-01-01"
  });

  assert.equal(missingCurrency.ok, false);
  assert.equal(invalidQuantity.ok, false);
  assert.equal(invalidDate.ok, false);
  assert.equal(overPrecision.ok, false);
});
