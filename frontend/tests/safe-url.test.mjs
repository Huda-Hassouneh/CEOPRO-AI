import test from 'node:test';
import assert from 'node:assert/strict';
import { safeHref } from '../src/shared/lib/safeUrl.js';

test('web addresses are linked', () => {
  assert.equal(safeHref('https://example.com/a?b=1'), 'https://example.com/a?b=1');
  assert.equal(safeHref('http://example.com'), 'http://example.com');
  assert.equal(safeHref('  HTTPS://Example.com  '), 'HTTPS://Example.com');
});

test('script and data addresses are never linked', () => {
  for (const url of ['javascript:alert(1)', 'JaVaScRiPt:alert(1)', ' javascript:alert(1)', 'data:text/html,<script>alert(1)</script>',
    'vbscript:msgbox(1)', '//evil.example/x', '/relative', 'ftp://example.com', 'file:///etc/passwd', 'java\tscript:alert(1)']) {
    assert.equal(safeHref(url), undefined, url);
  }
});

test('missing or non-string values are not linked', () => {
  for (const value of [undefined, null, 42, {}, []]) assert.equal(safeHref(value), undefined);
});
