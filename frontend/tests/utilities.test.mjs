// Sign-up and sign-in validation, error messages, where sign-in returns to,
// upload checks and plan-usage advice.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  firstValidationError, getPasswordRequirementState, validateConfirmPassword, validateCurrency, validateEmail,
  validatePassword, validateRequired, validateVerificationCode,
} from '../src/features/auth/validation/authValidation.js';
import { getPostLoginDestination } from '../src/features/auth/utils/authRouting.js';
import { getAuthErrorTranslationKey } from '../src/features/auth/utils/authErrors.js';
import { getInvalidUploadFile, MAX_UPLOAD_FILE_SIZE } from '../src/features/data-ingestion/utils/fileValidation.js';
import { formatMoney } from '../src/features/billing/utils/money.js';
import { getUpgradeRecommendation, getUsageState } from '../src/features/billing/utils/subscriptionRecommendations.js';

const keyOf = (result) => firstValidationError(result)?.key ?? null;

test('required and email fields', () => {
  assert.equal(keyOf(validateRequired('  ')), 'auth.validation.required');
  assert.equal(keyOf(validateRequired('Lina')), null);
  assert.equal(keyOf(validateEmail('')), 'auth.validation.emailRequired');
  assert.equal(keyOf(validateEmail('not-an-email')), 'auth.validation.email');
  assert.equal(keyOf(validateEmail('lina@example.com')), null);
});

test('passwords need length, both cases, a number and a symbol - every missing rule is reported', () => {
  assert.equal(keyOf(validatePassword('')), 'auth.validation.passwordRequired');
  const weak = validatePassword('abc');
  assert.deepEqual(weak.errors.map((e) => e.key), [
    'auth.validation.passwordLength', 'auth.validation.passwordUppercase', 'auth.validation.passwordNumber', 'auth.validation.passwordSpecial',
  ]);
  assert.equal(weak.errors[0].params.min, 8);
  assert.equal(validatePassword('Strong!Pass1').valid, true);
  assert.deepEqual(getPasswordRequirementState('Aa1!').map((r) => [r.id, r.met]),
    [['minLength', false], ['uppercase', true], ['lowercase', true], ['number', true], ['special', true]]);
});

test('password confirmation, currency and the 6-digit code', () => {
  assert.equal(keyOf(validateConfirmPassword('Strong!Pass1', '')), 'auth.validation.confirmPasswordRequired');
  assert.equal(keyOf(validateConfirmPassword('Strong!Pass1', 'Strong!Pass2')), 'auth.validation.passwordMismatch');
  assert.equal(keyOf(validateConfirmPassword('Strong!Pass1', 'Strong!Pass1')), null);
  assert.equal(keyOf(validateCurrency('')), 'auth.validation.currencyRequired');
  assert.equal(keyOf(validateCurrency('JO')), 'auth.validation.currency');
  assert.equal(keyOf(validateCurrency('jod')), null);
  assert.equal(keyOf(validateVerificationCode('12 34 56')), null, 'spaces are ignored');
  assert.equal(keyOf(validateVerificationCode('12345')), 'auth.validation.verificationCode');
});

test('sign-in opens the Dashboard, resuming only an invitation or a checkout return', () => {
  assert.equal(getPostLoginDestination({ from: { pathname: '/marketing' } }), '/dashboard', 'not the page a session expired on');
  assert.equal(getPostLoginDestination({ from: '/pricing' }), '/dashboard');
  assert.equal(getPostLoginDestination({ from: { pathname: '/invitation', search: '?token=abc' } }), '/invitation?token=abc');
  assert.equal(getPostLoginDestination({ from: { pathname: '/billing', search: '?checkout=success' } }), '/billing?checkout=success');
  assert.equal(getPostLoginDestination({ from: '//evil.example/steal' }), '/dashboard', 'no protocol-relative redirect');
  assert.equal(getPostLoginDestination({ from: 'https://evil.example' }), '/dashboard');
  assert.equal(getPostLoginDestination(undefined), '/dashboard');
});

test('sign-in errors become the right message', () => {
  const failure = (status, data = {}) => ({ response: { status, data } });
  assert.equal(getAuthErrorTranslationKey(new Error('offline')), 'auth.errors.network');
  assert.equal(getAuthErrorTranslationKey(failure(400, { code: 'CODE_EXPIRED' })), 'auth.errors.expiredCode');
  assert.equal(getAuthErrorTranslationKey(failure(401), { unauthorizedKey: 'auth.errors.invalidCredentials' }), 'auth.errors.invalidCredentials');
  assert.equal(getAuthErrorTranslationKey(failure(429)), 'auth.errors.tooManyAttempts');
  assert.equal(getAuthErrorTranslationKey(failure(503)), 'auth.errors.serverUnavailable');
  assert.equal(getAuthErrorTranslationKey(failure(409), { fallbackKey: 'auth.errors.emailInUse' }), 'auth.errors.emailInUse');
});

test('uploads accept only what the server reads, up to its size limit', () => {
  const file = (name, size = 100) => ({ name, size });
  assert.equal(getInvalidUploadFile([file('sales.csv'), file('Report.XLSX'), file('menu.pdf'), file('macro.xlsm')]), null);
  assert.equal(getInvalidUploadFile([file('sales.csv'), file('photo.png')]).name, 'photo.png');
  assert.equal(getInvalidUploadFile([file('old.xls')]).name, 'old.xls');
  assert.equal(getInvalidUploadFile([file('big.csv', MAX_UPLOAD_FILE_SIZE + 1)]).name, 'big.csv');
  assert.equal(getInvalidUploadFile([file('limit.csv', MAX_UPLOAD_FILE_SIZE)]), null);
});

test('money is formatted in the company currency and language', () => {
  assert.equal(formatMoney(null, 'JOD', 'en'), '');
  assert.match(formatMoney(12.5, 'JOD', 'en'), /JOD\s?12\.50/);
  assert.match(formatMoney(12.5, undefined, 'en'), /\$12\.50/);
});

test('plan usage: unlimited, approaching at 80%, reached at the limit', () => {
  assert.equal(getUsageState(5, null), 'unlimited');
  assert.equal(getUsageState(undefined, 10), 'unknown');
  assert.equal(getUsageState(7, 10), 'normal');
  assert.equal(getUsageState(8, 10), 'approaching');
  assert.equal(getUsageState(10, 10), 'reached');
  assert.equal(getUsageState(0, 0), 'notIncluded', 'a limit of 0 means the plan does not include it');
});

test('upgrade advice names the limit that blocked the action first', () => {
  const plan = (usage, extra = {}) => ({ planId: 'starter', status: 'active', limits: { products: 100, competitors: 10 }, usage, ...extra });
  assert.equal(getUpgradeRecommendation(null), null);
  assert.equal(getUpgradeRecommendation(plan({}, { planId: 'custom' })), null);
  assert.deepEqual(getUpgradeRecommendation(plan({}, { status: 'trial' })), { type: 'trial' });
  assert.deepEqual(getUpgradeRecommendation(plan({ products: 100, competitors: 10 }), 'competitor-limit'), { type: 'reached', key: 'competitors', contextual: true });
  assert.deepEqual(getUpgradeRecommendation(plan({ products: 100, competitors: 1 })), { type: 'reached', key: 'products' });
  assert.deepEqual(getUpgradeRecommendation(plan({ products: 85, competitors: 1 })), { type: 'approaching', key: 'products' });
  assert.equal(getUpgradeRecommendation(plan({ products: 10, competitors: 1 })), null);
});
