import test from 'node:test';
import assert from 'node:assert/strict';
import { cleanBarcode, isValidBarcode } from '../src/shared/utils/barcode.js';

test('barcodes are validated with the GS1 check digit, matching the server', () => {
  for (const good of ['3017620422003', '3017 6204-22003', '036000291452', '96385074', '6221031020018']) assert.equal(isValidBarcode(good), true, good);
  for (const bad of ['3017620422004', '12345', '30176204220AB', '0360002914521', '', null, undefined]) assert.equal(isValidBarcode(bad), false, String(bad));
  assert.equal(cleanBarcode(' 3017 6204-22003 '), '3017620422003');
});
