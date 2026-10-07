import test from 'node:test';
import assert from 'node:assert/strict';
import { getApiError, getApiErrorMessage } from '../src/shared/lib/apiErrorCore.js';

const translate = (key) => `localized:${key}`;

test('maps generic backend errors by their stable backend code', () => {
  const error = { response: { status: 404, data: { success: false, error: {
    code: 'PLAN_NOT_FOUND', message: 'Subscription plan not found', statusCode: 404
  } } } };
  assert.equal(getApiErrorMessage(error, translate), 'localized:apiErrors.PLAN_NOT_FOUND');
  assert.equal(getApiError(error).code, 'PLAN_NOT_FOUND');
});

test('preserves a specific server validation message instead of replacing it', () => {
  const error = { response: { status: 400, data: { error: {
    code: 'VALIDATION_ERROR', message: 'Missing required columns: sale_date, quantity'
  } } } };
  assert.equal(getApiErrorMessage(error, translate), 'Missing required columns: sale_date, quantity');
});

test('uses status and connectivity fallbacks when no useful backend code exists', () => {
  assert.equal(getApiErrorMessage({ response: { status: 403, data: {} } }, translate), 'localized:apiErrors.FORBIDDEN');
  assert.equal(getApiErrorMessage({ request: {} }, translate), 'localized:apiErrors.NETWORK');
});
