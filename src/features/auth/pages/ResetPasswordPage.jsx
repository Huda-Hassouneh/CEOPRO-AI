import React, { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import Button from '../../../shared/components/ui/Button.jsx';
import PasswordInput from '../../../shared/components/ui/PasswordInput.jsx';
import PasswordStrength from '../../../shared/components/ui/PasswordStrength.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { useResetPasswordMutation } from '../hooks/useResetPasswordMutation.js';
import { getAuthErrorTranslationKey } from '../utils/authErrors.js';
import { firstValidationError, getPasswordRequirementState, validateConfirmPassword, validatePassword } from '../validation/authValidation.js';
import { AuthBackLink, AuthPanel } from '../components/AuthPanel.jsx';
import { AuthStatusMessage } from '../components/AuthStatusMessage.jsx';
import { PasswordRequirements } from '../components/PasswordRequirements.jsx';
import '../styles/AuthForms.css';

export function ResetPasswordPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { locale, t } = useI18n();
  const [values, setValues] = useState({ password: '', confirmPassword: '' });
  const [errors, setErrors] = useState({});
  const [touched, setTouched] = useState({});
  const [passwordFocused, setPasswordFocused] = useState(false);
  const [requestError, setRequestError] = useState('');
  const metRequirements = getPasswordRequirementState(values.password).filter((requirement) => requirement.met).length;
  const score = metRequirements === 5 ? 4 : metRequirements >= 3 ? 3 : metRequirements >= 2 ? 2 : metRequirements > 0 ? 1 : 0;
  const strengthLabels = [
    t('auth.resetPassword.strengthWeak'),
    t('auth.resetPassword.strengthWeak'),
    t('auth.resetPassword.strengthFair'),
    t('auth.resetPassword.strengthGood'),
    t('auth.resetPassword.strengthStrong'),
  ];
  const mutation = useResetPasswordMutation({
    onSuccess: () => navigate(routePaths.login, { replace: true, state: { authNotice: 'password-reset' } }),
    onError: (requestFailure) => setRequestError(getAuthErrorTranslationKey(requestFailure)),
  });

  const translateError = (validation) => {
    const validationError = firstValidationError(validation);
    return validationError ? t(validationError.key, validationError.params) : '';
  };

  const validateField = (name, nextValues) => name === 'password'
    ? translateError(validatePassword(nextValues.password))
    : translateError(validateConfirmPassword(nextValues.password, nextValues.confirmPassword));

  const update = (name) => (event) => {
    const nextValues = { ...values, [name]: event.target.value };
    setValues(nextValues);
    setRequestError('');

    if (touched[name] || errors[name] || (name === 'confirmPassword' && nextValues.confirmPassword.length > 0)) {
      setTouched((current) => ({ ...current, [name]: true }));
      setErrors((current) => ({ ...current, [name]: validateField(name, nextValues) }));
    }
    if (name === 'password' && (touched.confirmPassword || nextValues.confirmPassword)) {
      setErrors((current) => ({ ...current, confirmPassword: validateField('confirmPassword', nextValues) }));
    }
  };

  const blurField = (name) => () => {
    setTouched((current) => ({ ...current, [name]: true }));
    setErrors((current) => ({ ...current, [name]: validateField(name, values) }));
  };

  React.useEffect(() => {
    setErrors((current) => ({
      ...current,
      ...(touched.password ? { password: validateField('password', values) } : {}),
      ...(touched.confirmPassword ? { confirmPassword: validateField('confirmPassword', values) } : {}),
    }));
  }, [locale]);

  const submit = (event) => {
    event.preventDefault();
    const passwordError = firstValidationError(validatePassword(values.password));
    const confirmationError = firstValidationError(validateConfirmPassword(values.password, values.confirmPassword));
    const nextErrors = {
      password: passwordError ? t(passwordError.key, passwordError.params) : '',
      confirmPassword: confirmationError ? t(confirmationError.key, confirmationError.params) : '',
    };
    setTouched({ password: true, confirmPassword: true });
    setErrors(nextErrors);
    setRequestError('');
    if (nextErrors.password || nextErrors.confirmPassword) return;
    mutation.mutate({ ...values, email: location.state?.email, code: location.state?.code });
  };

  return (
    <AuthPanel title={t('auth.resetPassword.title')} subtitle={t('auth.resetPassword.subtitle')} className="ceopro-auth-body--narrow">
      <AuthStatusMessage>{requestError ? t(requestError) : ''}</AuthStatusMessage>
      <form className="ceopro-auth-form" onSubmit={submit} noValidate>
        <PasswordInput label={t('auth.common.newPassword')} showPasswordLabel={t('auth.common.showPassword')} hidePasswordLabel={t('auth.common.hidePassword')} autoComplete="new-password" placeholder={t('auth.resetPassword.newPlaceholder')} value={values.password} error={errors.password} onChange={update('password')} onFocus={() => setPasswordFocused(true)} onBlur={() => { setPasswordFocused(false); blurField('password')(); }} disabled={mutation.isPending} />
        <PasswordRequirements password={values.password} visible={passwordFocused} />
        {(passwordFocused || values.password.length > 0 || touched.password) && <PasswordStrength score={score} title={t('auth.resetPassword.strength')} label={strengthLabels[score]} hint={t('auth.resetPassword.hint')} />}
        <PasswordInput label={t('auth.common.confirmNewPassword')} showPasswordLabel={t('auth.common.showPassword')} hidePasswordLabel={t('auth.common.hidePassword')} autoComplete="new-password" placeholder={t('auth.resetPassword.confirmPlaceholder')} value={values.confirmPassword} error={errors.confirmPassword} onChange={update('confirmPassword')} onBlur={blurField('confirmPassword')} disabled={mutation.isPending} />
        <Button type="submit" variant="primary" fullWidth loading={mutation.isPending} loadingLabel={t('auth.loading.resetting')}>{t('auth.resetPassword.submit')}</Button>
      </form>
      <AuthBackLink />
    </AuthPanel>
  );
}
