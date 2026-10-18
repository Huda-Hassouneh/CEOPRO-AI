export const AUTH_API_MODE = Object.freeze({ MOCK: 'mock', HTTP: 'http' });

// Isolated placeholders: update these when the backend contract is finalized.
export const authEndpoints = Object.freeze({
  login: '/auth/login',
  signup: '/auth/register',
  googleAuth: '/auth/google',
  forgotPassword: '/auth/password/forgot',
  verifyResetCode: '/auth/password/verify-code',
  resetPassword: '/auth/password/reset',
  resendVerification: '/auth/verification/resend',
  verifyEmail: '/auth/verification/exchange',
  invitation: '/auth/invitations',
  logout: '/auth/logout',
});

export const authQueryKeys = Object.freeze({
  invitation: (token) => ['auth', 'invitation', token],
});
