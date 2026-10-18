export const authEndpoints = Object.freeze({
  login: '/auth/login',
  signup: '/auth/signup',
  forgotPassword: '/auth/password/forgot',
  verifyResetCode: '/auth/password/verify-code',
  resetPassword: '/auth/password/reset',
  resendVerification: '/auth/email/resend-verification',
  verifyEmail: '/auth/email/verify',
  invitation: '/auth/invitations',
  logout: '/auth/logout',
  refresh: '/auth/refresh',
});

export const authQueryKeys = Object.freeze({
  invitation: (token) => ['auth', 'invitation', token],
});
