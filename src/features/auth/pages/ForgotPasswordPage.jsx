import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Mail } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';
import Input from '../../../shared/components/ui/Input.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { useForgotPasswordMutation } from '../hooks/useForgotPasswordMutation.js';
import { getAuthErrorTranslationKey } from '../utils/authErrors.js';
import { firstValidationError, validateEmail } from '../validation/authValidation.js';
import { AuthBackLink, AuthPanel } from '../components/AuthPanel.jsx';
import { AuthStatusMessage } from '../components/AuthStatusMessage.jsx';
import '../styles/AuthForms.css';

export function ForgotPasswordPage() {
  const navigate = useNavigate();
  const { locale, t } = useI18n();
  const [email, setEmail] = useState('');
  const [error, setError] = useState('');
  const [touched, setTouched] = useState(false);
  const [requestError, setRequestError] = useState('');
  const mutation = useForgotPasswordMutation({
    onSuccess: () => navigate(routePaths.verifyCode, { state: { email } }),
    onError: (requestFailure) => setRequestError(getAuthErrorTranslationKey(requestFailure)),
  });

  const validate = (value) => {
    const validationError = firstValidationError(validateEmail(value));
    return validationError ? t(validationError.key, validationError.params) : '';
  };

  const updateEmail = (event) => {
    const value = event.target.value;
    setEmail(value);
    setRequestError('');
    if (touched || error) setError(validate(value));
  };

  React.useEffect(() => {
    if (touched) setError(validate(email));
  }, [locale]);

  const submit = (event) => {
    event.preventDefault();
    const nextError = validate(email);
    setTouched(true);
    setError(nextError);
    setRequestError('');
    if (!nextError) mutation.mutate({ email });
  };

  return (
    <AuthPanel title={t('auth.forgotPassword.title')} subtitle={t('auth.forgotPassword.subtitle')} className="ceopro-auth-body--narrow">
      <AuthStatusMessage>{requestError ? t(requestError) : ''}</AuthStatusMessage>
      <form className="ceopro-auth-form" onSubmit={submit} noValidate>
        <Input label={t('auth.common.emailAddress')} type="email" autoComplete="email" placeholder={t('auth.forgotPassword.emailPlaceholder')} leftIcon={<Mail size={25} />} value={email} error={error} onChange={updateEmail} onBlur={() => { setTouched(true); setError(validate(email)); }} disabled={mutation.isPending} />
        <Button type="submit" variant="primary" fullWidth loading={mutation.isPending} loadingLabel={t('auth.loading.sendingCode')}>{t('auth.forgotPassword.submit')}</Button>
      </form>
      <AuthBackLink />
    </AuthPanel>
  );
}
