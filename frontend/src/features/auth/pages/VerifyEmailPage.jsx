import React from 'react';
import { readPendingRegistration, clearPendingRegistration, registrationFields } from '../pendingRegistration.js';
import { useLocation, useNavigate } from 'react-router-dom';
import Button from '../../../shared/components/ui/Button.jsx';
import VerificationCodeInput from '../../../shared/components/ui/VerificationCodeInput.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { signOut } from '../../../shared/components/layout/signOut.js';
import { authHttpAdapter } from '../api/authHttpAdapter.js';
import { useResendVerificationMutation } from '../hooks/useResendVerificationMutation.js';
import { useVerifyEmailMutation } from '../hooks/useVerifyEmailMutation.js';
import { useResendCooldown } from '../hooks/useResendCooldown.js';
import { needsEmailVerification } from '../sessionKeeper.js';
import { selectIsAuthenticated, useAuthStore } from '../store/authStore.js';
import { getAuthErrorTranslationKey } from '../utils/authErrors.js';
import { firstValidationError, validateVerificationCode } from '../validation/authValidation.js';
import { AuthPanel } from '../components/AuthPanel.jsx';
import { AuthStatusMessage } from '../components/AuthStatusMessage.jsx';
import '../styles/AuthForms.css';

// Confirms the email address with the 6-digit code sent at sign-up. While
// confirmation is required (backend REQUIRE_EMAIL_VERIFICATION) the app sends
// unconfirmed sign-ins here; otherwise it can be skipped and done later.
export function VerifyEmailPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { locale, t } = useI18n();
  const isAuthenticated = useAuthStore(selectIsAuthenticated);
  const required = useAuthStore((state) => state.emailVerificationBlocked || needsEmailVerification(state.accessToken));
  const pending = readPendingRegistration();
  const email = location.state?.email || useAuthStore.getState().user?.email || pending?.email || '';
  const fields = registrationFields(email);
  const [code, setCode] = React.useState('');
  const [error, setError] = React.useState('');
  const [requestMessage, setRequestMessage] = React.useState(null);
  const { isCoolingDown, remainingSeconds, startCooldown } = useResendCooldown(30);

  const finish = async (response) => {
    clearPendingRegistration();
    if (response?.access_token) {
      const { toSession } = await import('../api/authHttpAdapter.js');
      useAuthStore.getState().setSession(toSession(response));
      navigate(routePaths.dashboard, { replace: true });
      return;
    }
    if (!isAuthenticated) {
      navigate(routePaths.login, { replace: true, state: { authNotice: 'email-verified' } });
      return;
    }
    // A fresh token carries the confirmed state, so the app opens straight away.
    try {
      useAuthStore.getState().setAccessToken(await authHttpAdapter.refresh());
    } catch {
      // The next renewal picks it up; nothing is blocked once confirmed.
    }
    navigate(routePaths.dashboard, { replace: true });
  };

  const verifyMutation = useVerifyEmailMutation({
    onSuccess: finish,
    onError: (requestFailure) => setRequestMessage({
      tone: 'error',
      key: getAuthErrorTranslationKey(requestFailure, { fallbackKey: 'auth.errors.invalidCode' }),
    }),
  });
  const resendMutation = useResendVerificationMutation({
    onSuccess: (response) => {
      startCooldown();
      setRequestMessage(response?.delivery === 'unavailable' ? { tone: 'error', key: 'auth.errors.deliveryUnavailable' } : { tone: 'success', key: 'auth.success.codeResent' });
    },
    onError: (requestFailure) => setRequestMessage({
      tone: 'error',
      key: getAuthErrorTranslationKey(requestFailure, { fallbackKey: 'auth.errors.resendFailed' }),
    }),
  });

  const validate = (value) => {
    const validationError = firstValidationError(validateVerificationCode(value));
    return validationError ? t(validationError.key, validationError.params) : '';
  };

  React.useEffect(() => {
    if (error) setError(validate(code));
  // Re-translate visible errors when the language changes only; typing re-validates on its own.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locale]);

  const updateCode = (value) => {
    setCode(value);
    setRequestMessage(null);
    if (error) setError(validate(value));
  };

  const verify = (event) => {
    event.preventDefault();
    const nextError = validate(code);
    setError(nextError);
    setRequestMessage(null);
    if (!nextError) verifyMutation.mutate({ email, code, ...fields });
  };

  const resend = () => {
    if (isCoolingDown || resendMutation.isPending || !email) return;
    setRequestMessage(null);
    resendMutation.mutate({ email, ...fields });
  };

  const busy = verifyMutation.isPending || resendMutation.isPending;
  return (
    <AuthPanel
      title={t('auth.verifyEmail.title')}
      subtitle={<>{email ? <>{t('auth.verifyEmail.subtitlePrefix')} <bdi dir="ltr">{email}</bdi>.</> : t('auth.verifyEmail.subtitleGeneric')}{required ? <><br />{t('auth.verifyEmail.required')}</> : null}</>}
      className="ceopro-auth-body--narrow"
    >
      {pending?.delivery === 'unavailable' && !requestMessage ? <AuthStatusMessage tone="error">{t('auth.errors.deliveryUnavailable')}</AuthStatusMessage> : null}
      <AuthStatusMessage tone={requestMessage?.tone}>{requestMessage?.key ? t(requestMessage.key) : ''}</AuthStatusMessage>
      <form onSubmit={verify} noValidate>
        <div className="ceopro-auth-code-copy">
          <VerificationCodeInput value={code} onChange={updateCode} ariaLabel={t('auth.verifyEmail.inputLabel')} error={error} disabled={verifyMutation.isPending} />
          <p className="ceopro-auth-resend">
            {t('auth.verifyEmail.notReceived')}{' '}
            {isCoolingDown
              ? <span className="ceopro-auth-resend__cooldown" role="status">{t('auth.verifyEmail.resendIn', { seconds: remainingSeconds })}</span>
              : <button type="button" className="ceopro-auth-link ceopro-auth-text-button" onClick={resend} disabled={busy || !email}>{resendMutation.isPending ? t('auth.loading.resending') : t('auth.verifyEmail.resend')}</button>}
          </p>
        </div>
        <div className="ceopro-auth-code-actions"><Button type="submit" variant="primary" fullWidth loading={verifyMutation.isPending} disabled={resendMutation.isPending} loadingLabel={t('auth.loading.verifying')}>{t('auth.verifyEmail.submit')}</Button></div>
      </form>
      {isAuthenticated && !required
        ? <button type="button" className="ceopro-auth-link ceopro-auth-link--change-email ceopro-auth-text-button" onClick={() => navigate(routePaths.dashboard, { replace: true })}>{t('auth.verifyEmail.later')}</button>
        : null}
      {isAuthenticated && required
        ? <button type="button" className="ceopro-auth-link ceopro-auth-link--change-email ceopro-auth-text-button" onClick={() => signOut(useAuthStore.getState().clearSession, navigate)}>{t('auth.verifyEmail.signOut')}</button>
        : null}
      {!isAuthenticated
        ? <button type="button" className="ceopro-auth-link ceopro-auth-link--change-email ceopro-auth-text-button" onClick={() => navigate(routePaths.login)}>{t('auth.verifyEmail.backToLogin')}</button>
        : null}
    </AuthPanel>
  );
}
