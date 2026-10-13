export const EMAIL_PATTERN = /^[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+$/;

export const isNonEmpty = (value) => String(value ?? '').trim().length > 0;
export const isValidEmail = (value) => typeof value === 'string' && EMAIL_PATTERN.test(value.trim());
