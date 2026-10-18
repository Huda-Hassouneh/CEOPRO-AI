import test from 'node:test';
import assert from 'node:assert/strict';
import { getApiError, getApiErrorMessage } from '../src/shared/lib/apiErrorCore.js';

const translate = (key) => `localized:${key}`;

test('forecast errors show the known failure reason while unrelated or unknown reasons retain the generic message', () => {
  const error = { error: { code: 'EXTERNAL_SERVICE_ERROR', message: 'External service error', details: { service: 'AI forecasting service', reason: 'FORECAST_AI_TIMEOUT' } } };
  assert.equal(getApiErrorMessage(error, translate), 'localized:apiErrors.forecastingReasons.FORECAST_AI_TIMEOUT');
  error.error.details.service = 'other service';
  assert.equal(getApiErrorMessage(error, translate), 'localized:apiErrors.EXTERNAL_SERVICE_ERROR');
  error.error.details.service = 'AI forecasting service'; error.error.details.reason = 'secret_value';
  assert.equal(getApiErrorMessage(error, translate), 'localized:apiErrors.EXTERNAL_SERVICE_ERROR');
});

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

test('localizes the disconnected-source reactivation conflict by its stable code', () => {
  const error = { response: { status: 409, data: { error: {
    code: 'DATA_SOURCE_RECONNECT_REQUIRED',
    message: 'Reconnect this data source before it can be reactivated.',
    statusCode: 409
  } } } };
  assert.equal(getApiErrorMessage(error, translate), 'localized:apiErrors.DATA_SOURCE_RECONNECT_REQUIRED');
});
