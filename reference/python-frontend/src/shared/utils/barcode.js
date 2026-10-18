// Mirrors backend/src/ai/core/barcode.py so a typo is caught while typing; the server
// still validates. EAN-8, UPC-A, EAN-13 and GTIN-14 with the GS1 check digit.
const VALID_LENGTHS = [8, 12, 13, 14];

export function cleanBarcode(value) {
  return String(value ?? '').replace(/[\s-]/g, '');
}

export function isValidBarcode(value) {
  const text = cleanBarcode(value);
  if (!/^\d+$/.test(text) || !VALID_LENGTHS.includes(text.length)) return false;
  const body = text.slice(0, -1).split('').reverse();
  const total = body.reduce((sum, digit, index) => sum + Number(digit) * (index % 2 === 0 ? 3 : 1), 0);
  return (10 - (total % 10)) % 10 === Number(text.slice(-1));
}
