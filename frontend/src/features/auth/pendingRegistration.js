const KEY = 'keel_pending_registration';
let memory = null;
function storageOrNull(storage) {
  try { return storage ?? globalThis.sessionStorage ?? null; } catch { return null; }
}
export function savePendingRegistration(value, storage) {
  if (!value?.registration_token || !value?.email) return;
  memory = { email: value.email, registration_token: value.registration_token, delivery: value.delivery };
  try { storageOrNull(storage)?.setItem(KEY, JSON.stringify(memory)); } catch { /* Same-tab memory remains available. */ }
}
export function readPendingRegistration(storage) {
  try { return JSON.parse(storageOrNull(storage)?.getItem(KEY) || 'null') || memory; } catch { return memory; }
}
export function clearPendingRegistration(storage) {
  memory = null;
  try { storageOrNull(storage)?.removeItem(KEY); } catch { /* Already cleared in memory. */ }
}
export function registrationFields(email, storage) {
  const value = readPendingRegistration(storage);
  return value?.email?.toLowerCase() === email?.toLowerCase() ? { registration_token: value.registration_token } : {};
}
