import test from 'node:test';
import assert from 'node:assert/strict';
import { agreeArabicCounts } from '../src/shared/lib/arabicCounts.js';

test('Arabic day and order counts agree with the number (seen on keelai.net: "7 يومًا", "0 طلبًا")', () => {
  const day = (n) => agreeArabicCounts(`${n} يومًا`);
  assert.equal(day(0), '0 يوم');
  assert.equal(day(1), 'يوم واحد');
  assert.equal(day(2), 'يومان');
  assert.equal(day(3), '3 أيام');
  assert.equal(day(7), '7 أيام');
  assert.equal(day(10), '10 أيام');
  assert.equal(day(11), '11 يومًا');
  assert.equal(day(30), '30 يومًا');
  assert.equal(day(90), '90 يومًا');
  assert.equal(day(100), '100 يوم');
  assert.equal(day('1,203'), '1,203 أيام');
  assert.equal(day('٧'), '٧ أيام');
  const orders = (n) => agreeArabicCounts(`${n} طلبًا`);
  assert.equal(orders(0), '0 طلب');
  assert.equal(orders(1), 'طلب واحد');
  assert.equal(orders(2), 'طلبان');
  assert.equal(orders(5), '5 طلبات');
  assert.equal(orders(42), '42 طلبًا');
  const products = (n) => agreeArabicCounts(`${n} منتج`);
  assert.equal(products(1), 'منتج واحد');
  assert.equal(products(4), '4 منتجات');
  assert.equal(products(29), '29 منتجًا');
  assert.equal(products(100), '100 منتج');
  assert.equal(agreeArabicCounts('3 منتجات'), '3 منتجات');
  assert.equal(agreeArabicCounts('من 28 منتجًا متوقعًا'), 'من 28 منتجًا متوقعًا');
});

test('only a counted noun right after a whole number changes', () => {
  assert.equal(agreeArabicCounts('خلال الثلاثين يومًا القادمة'), 'خلال الثلاثين يومًا القادمة');
  assert.equal(agreeArabicCounts('يكفي المخزون نحو 7 يومًا بوتيرة التوقع'), 'يكفي المخزون نحو 7 أيام بوتيرة التوقع');
  assert.equal(agreeArabicCounts('حققت 22,406 د.أ. خلال آخر 7 يومًا.'), 'حققت 22,406 د.أ. خلال آخر 7 أيام.');
  assert.equal(agreeArabicCounts('2.5 يومًا'), '2.5 يومًا');
  assert.equal(agreeArabicCounts('Valid for 7 days'), 'Valid for 7 days');
});
