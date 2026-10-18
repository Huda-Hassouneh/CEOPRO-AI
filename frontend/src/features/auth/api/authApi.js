import { AUTH_API_MODE } from './authContracts.js';
import { authHttpAdapter } from './authHttpAdapter.js';
import { authMockAdapter } from './authMockAdapter.js';

// Real auth must be the default so signup/login never succeed silently in a
// mock adapter when the environment file was not copied from .env.example.
// Mock auth remains available as an explicit development opt-in.
export const authApiMode = import.meta.env.VITE_AUTH_API_MODE === AUTH_API_MODE.MOCK
  ? AUTH_API_MODE.MOCK
  : AUTH_API_MODE.HTTP;

const adapter = authApiMode === AUTH_API_MODE.HTTP ? authHttpAdapter : authMockAdapter;

export const authApi = Object.freeze({
  login: (payload) => adapter.login(payload),
  signup: (payload) => adapter.signup(payload),
  googleAuth: (payload) => adapter.googleAuth(payload),
  forgotPassword: (payload) => adapter.forgotPassword(payload),
  verifyResetCode: (payload) => adapter.verifyResetCode(payload),
  resetPassword: (payload) => adapter.resetPassword(payload),
  resendVerification: (payload) => adapter.resendVerification(payload),
  verifyEmail: (payload) => adapter.verifyEmail(payload),
  getInvitation: (token) => adapter.getInvitation(token),
  acceptInvitation: (payload) => adapter.acceptInvitation(payload),
  logout: (payload) => adapter.logout(payload),
});
