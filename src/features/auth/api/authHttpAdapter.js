import httpClient from '../../../shared/lib/httpClient.js';
import { authEndpoints } from './authContracts.js';

const unwrap = (request) => request.then((response) => response.data);

export const authHttpAdapter = Object.freeze({
  login: (payload) => unwrap(httpClient.post(authEndpoints.login, payload)),
  signup: (payload) => unwrap(httpClient.post(authEndpoints.signup, payload)),
  googleAuth: (payload) => unwrap(httpClient.post(authEndpoints.googleAuth, payload)),
  forgotPassword: (payload) => unwrap(httpClient.post(authEndpoints.forgotPassword, payload)),
  verifyResetCode: (payload) => unwrap(httpClient.post(authEndpoints.verifyResetCode, payload)),
  resetPassword: (payload) => unwrap(httpClient.post(authEndpoints.resetPassword, payload)),
  resendVerification: (payload) => unwrap(httpClient.post(authEndpoints.resendVerification, payload)),
  verifyEmail: (payload) => unwrap(httpClient.post(authEndpoints.verifyEmail, payload)),
  getInvitation: (token) => unwrap(httpClient.get(`${authEndpoints.invitation}/${encodeURIComponent(token)}`)),
  acceptInvitation: ({ token, ...payload }) => unwrap(httpClient.post(`${authEndpoints.invitation}/${encodeURIComponent(token)}/accept`, payload)),
  logout: (payload) => unwrap(httpClient.post(authEndpoints.logout, payload)),
});
