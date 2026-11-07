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
