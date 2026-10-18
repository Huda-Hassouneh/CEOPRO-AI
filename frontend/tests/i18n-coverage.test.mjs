import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { resources, verifyTranslations } from '../scripts/verify-i18n.mjs';
import { getRagErrorFeedback } from '../src/features/knowledge-base/utils/ragErrorFeedback.js';

// Exercise the application's actual translator without requiring a browser JSON loader.
const source = fs.readFileSync(new URL('../src/shared/lib/i18n.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?$/gm, '').replace(/\bexport /g, '');
const { translate, translateCurrent } = new Function('en', 'ar', 'landingEn', 'landingAr', 'adminEn', 'adminAr',
  `${source}; return { translate, translateCurrent };`)(resources.en, resources.ar, resources.en.landing,
    resources.ar.landing, resources.en.platformAdmin, resources.ar.platformAdmin);

test('English/Arabic key coverage and interpolation contracts', () => {
  assert.ok(verifyTranslations().keysPerLanguage > 1000);
});

test('switching language resolves shared control labels and complete count phrases', () => {
  for (const key of ['interfaceCopy.progress', 'interfaceCopy.noDataAvailable', 'interfaceCopy.dismissNotification',
    'auth.common.showPassword', 'billing.custom.selectedFeatureCount']) {
    assert.notEqual(translate('en', key, { count: 3 }), translate('ar', key, { count: 3 }));
    assert.doesNotMatch(translate('ar', key, { count: 3 }), /\{\{|interfaceCopy\./);
  }
  assert.equal(translate('ar', 'ragAssistant.sources.sourceDocument', { index: 12 }), 'المستند المصدر 12');
  assert.equal(translate('xx', 'common.close'), translate('en', 'common.close'));
});

test('non-React error messages follow the active document language', () => {
  const previous = globalThis.document;
  try {
    globalThis.document = { documentElement: { lang: 'ar' } };
    assert.equal(translateCurrent('interfaceCopy.checkoutUrlMissing'), resources.ar.interfaceCopy.checkoutUrlMissing);
    globalThis.document.documentElement.lang = 'en';
    assert.equal(translateCurrent('interfaceCopy.checkoutUrlMissing'), resources.en.interfaceCopy.checkoutUrlMissing);
  } finally {
    if (previous === undefined) delete globalThis.document; else globalThis.document = previous;
  }
});

test('RAG validation, capacity, permissions and network errors have both translations', () => {
  const samples = [
    [{ code: 'INVALID_FILE_UPLOAD' }, 'upload'],
    [{ response: { status: 413 } }, 'upload'],
    [{ response: { status: 402, data: { error: { details: { reason: 'CAPACITY_REACHED', requested: 512, remaining: 256, unit: 'KB' } } } } }, 'upload'],
    [{ response: { status: 403 } }, 'chat'],
    [{ response: { status: 401 } }, 'chat'],
    [{ code: 'VALIDATION_ERROR' }, 'chat'],
    [{ response: { status: 503 } }, 'chat'],
    [{ response: { status: 429 } }, 'chat'],
    [{ request: {} }, 'chat'],
  ];
  for (const locale of ['en', 'ar']) for (const [error, action] of samples) {
    const result = getRagErrorFeedback(error, { action, locale, t: (key, values) => translate(locale, key, values) });
    assert.ok(result.message);
    assert.doesNotMatch(result.message, /ragAssistant\.|\{\{/);
    if (locale === 'ar') assert.match(result.message, /[\u0600-\u06ff]/);
  }
});
