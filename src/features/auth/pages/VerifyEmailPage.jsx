import React from 'react';
import { Mail } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import Button from '../../../shared/components/ui/Button.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { useResendVerificationMutation } from '../hooks/useResendVerificationMutation.js';
import { useResendCooldown } from '../hooks/useResendCooldown.js';
import { getAuthErrorTranslationKey } from '../utils/authErrors.js';
import { AuthPanel } from '../components/AuthPanel.jsx';
import { AuthStatusMessage } from '../components/AuthStatusMessage.jsx';
import '../styles/AuthForms.css';

export function VerifyEmailPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { t } = useI18n();
  const email = location.state?.email || '';
  const [requestMessage, setRequestMessage] = React.useState(null);
  const { isCoolingDown, remainingSeconds, startCooldown } = useResendCooldown(30);
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
        <h1 className="ceopro-auth-title">{t('auth.verifyEmail.title')}</h1>
        <p className="ceopro-auth-subtitle">
          {email ? <>{t('auth.verifyEmail.subtitlePrefix')} <bdi>{email}</bdi>.</> : t('auth.verifyEmail.subtitleLine1')}<br />
          {t('auth.verifyEmail.subtitleLine2')}
        </p>
      </header>
      <AuthStatusMessage tone={requestMessage?.tone}>{requestMessage?.key ? t(requestMessage.key) : ''}</AuthStatusMessage>
      <Button
        variant="primary"
        fullWidth
        leadingIcon={<Mail size={18} aria-hidden="true" />}
        loading={resendMutation.isPending}
        disabled={isCoolingDown}
        loadingLabel={t('auth.loading.resending')}
        onClick={resend}
      >
        {isCoolingDown ? t('auth.verifyEmail.resendIn', { seconds: remainingSeconds }) : t('auth.verifyEmail.resend')}
      </Button>
      <button
        type="button"
        className="ceopro-auth-link ceopro-auth-link--change-email ceopro-auth-text-button"
        onClick={() => navigate(routePaths.signup, { state: email ? { email } : undefined })}
      >
        {t('auth.verifyEmail.changeEmail')}
      </button>
    </AuthPanel>
  );
}
