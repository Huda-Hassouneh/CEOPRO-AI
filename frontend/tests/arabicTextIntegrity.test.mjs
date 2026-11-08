import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Arabic saved through a non-UTF-8 path turns into '?????' and still passes the
// key-parity checks; this was live for the session-expired and checkout messages.
const walk = (value, path = []) => (typeof value === 'string'
  ? [[path.join('.'), value]]
  : Object.entries(value ?? {}).flatMap(([key, child]) => walk(child, [...path, key])));

for (const file of ['../src/assets/locales/ar.json', '../src/features/landing/locales/ar.json']) {
  test(`${file} has no text lost to question marks`, () => {
    const messages = JSON.parse(readFileSync(new URL(file, import.meta.url), 'utf8'));
    const broken = walk(messages).filter(([, text]) => /\?{3,}/.test(text)).map(([key]) => key);
    assert.deepEqual(broken, []);
  });
}

// UTF-8 Arabic decoded as Windows-1252 turns into 'Ø§Ù„...' (mojibake) and also passes key parity;
// this was live for every Arabic label of the Platform Owner portal (288 strings) from 25 Oct 2026.
const MOJIBAKE = /[ØÙÚÛ][\u0080-\u00bf\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u0192\u02c6\u02dc\u2013-\u2122]/;

for (const file of ['../src/assets/locales/ar.json', '../src/features/landing/locales/ar.json']) {
  test(`${file} has no Arabic garbled by a wrong encoding`, () => {
    const messages = JSON.parse(readFileSync(new URL(file, import.meta.url), 'utf8'));
    assert.deepEqual(walk(messages).filter(([, text]) => MOJIBAKE.test(text)).map(([key]) => key), []);
  });
}

test('platform administration Arabic labels are real Arabic, not garbled or lost', async () => {
  const { en, ar } = await import('../src/features/platform-admin/locales/messages.js');
  const texts = walk(ar);
  assert.deepEqual(texts.filter(([, text]) => MOJIBAKE.test(text) || /\?{3,}/.test(text)).map(([key]) => key), []);
  assert.deepEqual(Object.keys(ar).sort(), Object.keys(en).sort());
  // Most labels are translated; the brand name and a few codes may stay in Latin script.
  const arabic = texts.filter(([, text]) => /[\u0600-\u06ff]/.test(text)).length;
  assert.ok(arabic / texts.length > 0.8, `only ${arabic} of ${texts.length} Arabic labels contain Arabic letters`);
});
