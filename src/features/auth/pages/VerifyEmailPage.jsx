import React from 'react';
import { Mail } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import Button from '../../../shared/components/ui/Button.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { useResendVerificationMutation } from '../hooks/useResendVerificationMutation.js';
import { useVerifyEmailMutation } from '../hooks/useVerifyEmailMutation.js';
import { useResendCooldown } from '../hooks/useResendCooldown.js';
import { getAuthErrorTranslationKey } from '../utils/authErrors.js';
import { useAuthStore } from '../store/authStore.js';
import { useOnboardingStore } from '../../onboarding/store/onboardingStore.js';
import { AuthPanel } from '../components/AuthPanel.jsx';
import { AuthStatusMessage } from '../components/AuthStatusMessage.jsx';
import '../styles/AuthForms.css';

export function VerifyEmailPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { t } = useI18n();
  const email = location.state?.email || '';
  const query = new URLSearchParams(location.search);
  const code = query.get('code');
  const token = query.get('token');
  const validToken = typeof token === 'string' && /^[a-f0-9]{64}$/i.test(token);
  const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:5000').replace(/\/$/, '');
  const setSession = useAuthStore((state) => state.setSession);
  const [requestMessage, setRequestMessage] = React.useState(null);
  const exchangeStarted = React.useRef(null);
  const { isCoolingDown, remainingSeconds, startCooldown } = useResendCooldown(30);
  const verifyMutation = useVerifyEmailMutation({
    onSuccess: (response) => {
      if (!response?.session) {
        setRequestMessage({ tone: 'error', key: 'auth.errors.verificationFailed' });
        return;
      }
      useOnboardingStore.getState().resetOnboarding();
      setSession(response.session);
      navigate(routePaths.onboardingWelcome, { replace: true });
    },
    onError: (requestFailure) => setRequestMessage({
      tone: 'error',
      key: getAuthErrorTranslationKey(requestFailure, { fallbackKey: 'auth.errors.verificationFailed' }),
    }),
  });
  const resendMutation = useResendVerificationMutation({
    onSuccess: () => {
      startCooldown();
      setRequestMessage({ tone: 'success', key: 'auth.success.verificationResent' });
    },
    onError: (requestFailure) => setRequestMessage({
      tone: 'error',
      key: getAuthErrorTranslationKey(requestFailure, { fallbackKey: 'auth.errors.resendFailed' }),
    }),
  });

  React.useEffect(() => {
    if (!code || exchangeStarted.current === code) return;
    exchangeStarted.current = code;
    verifyMutation.mutate({ code });
  }, [code]);

  const resend = () => {
    if (isCoolingDown || resendMutation.isPending) return;
    setRequestMessage(null);
    resendMutation.mutate(email ? { email } : {});
  };

  return (
    <AuthPanel className="ceopro-auth-body--narrow ceopro-auth-notice">
      <div className="ceopro-auth-notice-icon" aria-hidden="true">
        <Mail />
      </div>
      <header className="ceopro-auth-header">
        <h1 className="ceopro-auth-title">
          {code
            ? t('auth.verifyEmail.confirming')
            : validToken
              ? t('auth.verifyEmail.confirmTitle')
              : t('auth.verifyEmail.title')}
        </h1>
        <p className="ceopro-auth-subtitle">
          {code
            ? t('auth.verifyEmail.confirmingDescription')
            : validToken
              ? t('auth.verifyEmail.confirmDescription')
              : <>{email ? <>{t('auth.verifyEmail.subtitlePrefix')} <bdi>{email}</bdi>.</> : t('auth.verifyEmail.subtitleLine1')}<br />
                  {t('auth.verifyEmail.subtitleLine2')}</>}
        </p>
      </header>
      <AuthStatusMessage tone={requestMessage?.tone}>{requestMessage?.key ? t(requestMessage.key) : ''}</AuthStatusMessage>
      {validToken && !code && <form method="post" action={`${apiBaseUrl}/auth/verify-email/confirm`}>
        <input type="hidden" name="token" value={token} />
        <Button type="submit" variant="primary" fullWidth leadingIcon={<Mail size={18} aria-hidden="true" />}>
          {t('auth.verifyEmail.confirmButton')}
        </Button>
      </form>}
      {!code && !token && <Button
        variant="primary"
        fullWidth
        leadingIcon={<Mail size={18} aria-hidden="true" />}
        loading={resendMutation.isPending}
        disabled={isCoolingDown}
        loadingLabel={t('auth.loading.resending')}
        onClick={resend}
      >
        {isCoolingDown ? t('auth.verifyEmail.resendIn', { seconds: remainingSeconds }) : t('auth.verifyEmail.resend')}
      </Button>}
      {!code && !token && <button
        type="button"
        className="ceopro-auth-link ceopro-auth-link--change-email ceopro-auth-text-button"
        onClick={() => navigate(routePaths.signup, { state: email ? { email } : undefined })}
      >
        {t('auth.verifyEmail.changeEmail')}
      </button>}
    </AuthPanel>
  );
}
