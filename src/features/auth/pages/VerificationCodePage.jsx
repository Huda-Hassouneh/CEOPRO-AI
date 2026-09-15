import React, { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import Button from '../../../shared/components/ui/Button.jsx';
import VerificationCodeInput from '../../../shared/components/ui/VerificationCodeInput.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { useForgotPasswordMutation } from '../hooks/useForgotPasswordMutation.js';
import { useVerifyCodeMutation } from '../hooks/useVerifyCodeMutation.js';
import { useResendCooldown } from '../hooks/useResendCooldown.js';
import { getAuthErrorTranslationKey } from '../utils/authErrors.js';
import { firstValidationError, validateVerificationCode } from '../validation/authValidation.js';
import { AuthBackLink, AuthPanel } from '../components/AuthPanel.jsx';
import { AuthStatusMessage } from '../components/AuthStatusMessage.jsx';
import '../styles/AuthForms.css';

export function VerificationCodePage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { locale, t } = useI18n();
  const email = location.state?.email || '';
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [requestMessage, setRequestMessage] = useState(null);
  const { isCoolingDown, remainingSeconds, startCooldown } = useResendCooldown(30);
  const verifyMutation = useVerifyCodeMutation({
    onSuccess: () => navigate(routePaths.resetPassword, { state: { email, code } }),
    onError: (requestFailure) => setRequestMessage({
      tone: 'error',
      key: getAuthErrorTranslationKey(requestFailure, { fallbackKey: 'auth.errors.invalidCode' }),
    }),
  });
  const resendMutation = useForgotPasswordMutation({
    onSuccess: () => {
      startCooldown();
      setRequestMessage({ tone: 'success', key: 'auth.success.codeResent' });
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

  const updateCode = (value) => {
    setCode(value);
    setRequestMessage(null);
    if (error) setError(validate(value));
  };

  React.useEffect(() => {
    if (error) setError(validate(code));
  }, [locale]);

  const verify = (event) => {
    event.preventDefault();
    const nextError = validate(code);
    setError(nextError);
    setRequestMessage(null);
    if (!nextError) verifyMutation.mutate({ email, code });
  };

  const resend = () => {
    if (isCoolingDown || resendMutation.isPending) return;
    setRequestMessage(null);
    resendMutation.mutate({ email });
  };

  return (
    <AuthPanel title={t('auth.verificationCode.title')} subtitle={email ? <>{t('auth.verificationCode.subtitlePrefix')} <bdi>{email}</bdi>.</> : t('auth.verificationCode.subtitleGeneric')} className="ceopro-auth-body--narrow">
      <AuthStatusMessage tone={requestMessage?.tone}>{requestMessage?.key ? t(requestMessage.key) : ''}</AuthStatusMessage>
      <form onSubmit={verify} noValidate>
        <div className="ceopro-auth-code-copy">
          <VerificationCodeInput value={code} onChange={updateCode} ariaLabel={t('auth.verificationCode.inputLabel')} error={error} disabled={verifyMutation.isPending} />
          <p className="ceopro-auth-resend">
            {t('auth.verificationCode.notReceived')}{' '}
            {isCoolingDown
              ? <span className="ceopro-auth-resend__cooldown" role="status">{t('auth.verificationCode.resendIn', { seconds: remainingSeconds })}</span>
              : <button type="button" className="ceopro-auth-link ceopro-auth-text-button" onClick={resend} disabled={resendMutation.isPending || verifyMutation.isPending}>{resendMutation.isPending ? t('auth.loading.resending') : t('auth.verificationCode.resend')}</button>}
          </p>
        </div>
        <div className="ceopro-auth-code-actions"><Button type="submit" variant="primary" fullWidth loading={verifyMutation.isPending} disabled={resendMutation.isPending} loadingLabel={t('auth.loading.verifying')}>{t('auth.verificationCode.submit')}</Button></div>
      </form>
      <AuthBackLink />
    </AuthPanel>
  );
}
