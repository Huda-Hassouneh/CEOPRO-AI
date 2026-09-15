import { isValidEmail } from '../../../shared/utils/validators.js';

export const AUTH_PASSWORD_MIN_LENGTH = 8;
export const AUTH_VERIFICATION_CODE_LENGTH = 6;

const result = (errors = []) => ({ valid: errors.length === 0, errors });
const error = (key, params = {}) => ({ key, params });

export const AUTH_PASSWORD_REQUIREMENTS = Object.freeze([
  Object.freeze({
    id: 'minLength',
    labelKey: 'auth.passwordRequirements.minLength',
    errorKey: 'auth.validation.passwordLength',
    params: { min: AUTH_PASSWORD_MIN_LENGTH },
    test: (password) => password.length >= AUTH_PASSWORD_MIN_LENGTH,
  }),
  Object.freeze({
    id: 'uppercase',
    labelKey: 'auth.passwordRequirements.uppercase',
    errorKey: 'auth.validation.passwordUppercase',
    test: (password) => /[A-Z]/.test(password),
  }),
  Object.freeze({
    id: 'lowercase',
    labelKey: 'auth.passwordRequirements.lowercase',
    errorKey: 'auth.validation.passwordLowercase',
    test: (password) => /[a-z]/.test(password),
  }),
  Object.freeze({
    id: 'number',
    labelKey: 'auth.passwordRequirements.number',
    errorKey: 'auth.validation.passwordNumber',
    test: (password) => /\d/.test(password),
  }),
  Object.freeze({
    id: 'special',
    labelKey: 'auth.passwordRequirements.special',
    errorKey: 'auth.validation.passwordSpecial',
    test: (password) => /[^A-Za-z\d]/.test(password),
  }),
]);

export function validateRequired(value, { messageKey = 'auth.validation.required' } = {}) {
  return result(String(value ?? '').trim() ? [] : [error(messageKey)]);
}

export function validateEmail(value, { requiredKey = 'auth.validation.emailRequired' } = {}) {
  const required = validateRequired(value, { messageKey: requiredKey });
  if (!required.valid) return required;
  return result(isValidEmail(value) ? [] : [error('auth.validation.email')]);
}

export function getPasswordRequirementState(value) {
  const password = String(value ?? '');
  return AUTH_PASSWORD_REQUIREMENTS.map((requirement) => ({
    id: requirement.id,
    labelKey: requirement.labelKey,
    errorKey: requirement.errorKey,
    params: requirement.params ?? {},
    met: requirement.test(password),
  }));
}

export function validatePassword(value, { requiredKey = 'auth.validation.passwordRequired' } = {}) {
  const password = String(value ?? '');
  if (!password) return result([error(requiredKey)]);

  return result(getPasswordRequirementState(password)
    .filter((requirement) => !requirement.met)
    .map((requirement) => error(requirement.errorKey, requirement.params)));
}

export function validateConfirmPassword(password, confirmation, { requiredKey = 'auth.validation.confirmPasswordRequired' } = {}) {
  const required = validateRequired(confirmation, { messageKey: requiredKey });
  if (!required.valid) return required;
  return result(password === confirmation ? [] : [error('auth.validation.passwordMismatch')]);
}

export function validateVerificationCode(code, { length = AUTH_VERIFICATION_CODE_LENGTH } = {}) {
  const normalizedCode = String(code ?? '').replace(/\D/g, '');
  return result(normalizedCode.length === length
    ? []
    : [error('auth.validation.verificationCode', { length })]);
}

export function firstValidationError(validationResult) {
  return validationResult?.errors?.[0] ?? null;
}
