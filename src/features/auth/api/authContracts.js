export const AUTH_API_MODE = Object.freeze({ MOCK: 'mock', HTTP: 'http' });

// Isolated placeholders: update these when the backend contract is finalized.
export const authEndpoints = Object.freeze({
  login: '/auth/login',
  signup: '/auth/signup',
  googleAuth: '/auth/google',
  forgotPassword: '/auth/password/forgot',
  verifyResetCode: '/auth/password/verify-code',
  resetPassword: '/auth/password/reset',
  resendVerification: '/auth/email/resend-verification',
  verifyEmail: '/auth/email/verify',
  invitation: '/auth/invitations',
  logout: '/auth/logout',
});

export const authQueryKeys = Object.freeze({
  invitation: (token) => ['auth', 'invitation', token],
});
