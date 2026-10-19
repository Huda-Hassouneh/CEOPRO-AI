import { authHttpAdapter as adapter } from './authHttpAdapter.js';

export const authApi = Object.freeze({
  login: (payload) => adapter.login(payload),
  signup: (payload) => adapter.signup(payload),
  forgotPassword: (payload) => adapter.forgotPassword(payload),
  verifyResetCode: (payload) => adapter.verifyResetCode(payload),
  resetPassword: (payload) => adapter.resetPassword(payload),
  resendVerification: (payload) => adapter.resendVerification(payload),
  verifyEmail: (payload) => adapter.verifyEmail(payload),
  getInvitation: (token) => adapter.getInvitation(token),
  acceptInvitation: (payload) => adapter.acceptInvitation(payload),
  logout: (payload) => adapter.logout(payload),
});
