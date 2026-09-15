import { getInvitationPreview } from '../mocks/authPreviewData.js';

const mockResponse = (operation, payload) => Promise.resolve({
  ok: true,
  operation,
  payload,
  session: null,
  mock: true,
});

// Development-only behavior. No session is returned, so mocks cannot bypass guards.
export const authMockAdapter = Object.freeze({
  login: (payload) => mockResponse('login', payload),
  signup: (payload) => mockResponse('signup', payload),
  googleAuth: (payload) => mockResponse('googleAuth', payload),
  forgotPassword: (payload) => mockResponse('forgotPassword', payload),
  verifyResetCode: (payload) => mockResponse('verifyResetCode', payload),
  resetPassword: (payload) => mockResponse('resetPassword', payload),
  resendVerification: (payload) => mockResponse('resendVerification', payload),
  verifyEmail: (payload) => mockResponse('verifyEmail', payload),
  getInvitation: (token) => Promise.resolve({
    ok: true,
    operation: 'getInvitation',
    payload: { token },
    invitation: getInvitationPreview(String(token).toLowerCase().includes('expired') ? 'expired' : 'active'),
    session: null,
    mock: true,
  }),
  acceptInvitation: (payload) => mockResponse('acceptInvitation', payload),
  logout: (payload) => mockResponse('logout', payload),
});
