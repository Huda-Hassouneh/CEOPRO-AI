import { authApi } from '../../../features/auth/api/authApi.js';

// Revokes the token server-side, then always clears the local session -
// signing out must never depend on the network.
export async function signOut(clearSession, navigate) {
  try {
    await authApi.logout();
  } catch {
    // ignored on purpose
  }
  clearSession();
  navigate('/login', { replace: true });
}
