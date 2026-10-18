import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { getDataTemplateOptions } from '../src/features/data-ingestion/config/dataTemplateOptions.js';
import { formatImportIssue } from '../src/features/data-ingestion/utils/importIssueMessage.js';
import {
  getInvalidBusinessUploadFile,
  getInvalidStructuredBusinessUploadFile
} from '../src/features/data-ingestion/utils/fileValidation.js';

test('invoice and inventory modes offer their own CSV/XLSX templates while sales keeps its original choices', () => {
  assert.deepEqual(getDataTemplateOptions('sales').map(({ id }) => id), ['xlsx', 'csv']);
  assert.deepEqual(getDataTemplateOptions('invoices').map(({ id }) => id), ['invoices_xlsx', 'invoices_csv']);
  assert.deepEqual(getDataTemplateOptions('inventory').map(({ id }) => id), ['inventory_xlsx', 'inventory_csv']);
});

test('manual structured imports accept CSV/XLSX within 10 MiB and leave sales formats intact', () => {
  assert.equal(getInvalidStructuredBusinessUploadFile([{ name: 'invoices.csv', size: 10 }]), null);
  assert.equal(getInvalidStructuredBusinessUploadFile([{ name: 'inventory.xlsx', size: 10 }]), null);
  assert.equal(getInvalidStructuredBusinessUploadFile([{ name: 'inventory.pdf', size: 10 }]).name, 'inventory.pdf');
  assert.equal(getInvalidStructuredBusinessUploadFile([{ name: 'inventory.csv', size: 10 * 1024 * 1024 + 1 }]).name, 'inventory.csv');
  assert.equal(getInvalidBusinessUploadFile([{ name: 'sales.pdf', size: 10 }]), null);
});

test('both languages explain customer-readable imports, review, and incomplete coverage', () => {
  for (const locale of ['en', 'ar']) {
    const json = JSON.parse(readFileSync(new URL(`../src/assets/locales/${locale}.json`, import.meta.url), 'utf8'));
    assert.ok(json.connectData.upload.productReference);
    assert.ok(json.connectData.upload.help.invoices);
    assert.ok(json.connectData.upload.help.inventory);
    assert.ok(json.connectData.review.confirmImport);
    assert.ok(json.connectData.review.creationUnavailable);
    assert.ok(json.connectData.review.issues.date);
    assert.ok(json.dashboard.inventory.coverage);
    assert.ok(json.dashboard.sales.excludedCurrency);
    assert.ok(json.dataStatus.partial.label);
  }
});

test('common row errors render localized text while retaining their sheet and row in the UI', () => {
  const ar = JSON.parse(readFileSync(new URL('../src/assets/locales/ar.json', import.meta.url), 'utf8'));
  const translateIssue = (key) => ar.connectData.review.issues[key.split('.').at(-1)];
  assert.equal(formatImportIssue('issue_date must use YYYY-MM-DD.', translateIssue), ar.connectData.review.issues.date);
  assert.equal(formatImportIssue('Spreadsheet formulas are not allowed in import files.', translateIssue), ar.connectData.review.issues.formula);
});
