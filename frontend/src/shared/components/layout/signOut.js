import { authApi } from '../../../features/auth/api/authApi.js';

// Always clear this device. Tell the user if server revocation was not confirmed.
export async function signOut(clearSession, navigate) {
  let confirmed = false;
  try { const result = await authApi.logout(); confirmed = result?.revoked === true; } catch { /* Local sign-out still works. */ }
  clearSession();
  navigate('/login', { replace: true, state: confirmed ? {} : { authNotice: 'logout-unconfirmed' } });
}
