import test from 'node:test';
import assert from 'node:assert/strict';
import { getCreditBudgetState } from '../src/features/billing/utils/creditBudgetState.js';

test('Credit summary distinguishes unlimited, absent, disabled, and unavailable states', () => {
  assert.equal(getCreditBudgetState({ limit: null, consumed: 14, reserved: 2, remaining: null }), 'unlimited');
  assert.equal(getCreditBudgetState({ limit: 0, consumed: 0, reserved: 0, remaining: 0 }), 'notIncluded');
  assert.equal(getCreditBudgetState(undefined), 'unknown');
  assert.equal(getCreditBudgetState({ limit: 100, consumed: 15, reserved: 0 }), 'unknown');
});

test('Credit summary reflects retained reservations and configured warning state', () => {
  assert.equal(getCreditBudgetState({ limit: 100, consumed: 99, reserved: 1, remaining: 0 }), 'reached');
  assert.equal(getCreditBudgetState({ limit: 100, consumed: 40, reserved: 5, remaining: 55, warning: 40 }), 'approaching');
  assert.equal(getCreditBudgetState({ limit: 100, consumed: 39, reserved: 5, remaining: 56, warning: null }), 'normal');
});
