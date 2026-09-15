import React, { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import Button from '../../../shared/components/ui/Button.jsx';
import Checkbox from '../../../shared/components/ui/Checkbox.jsx';
import GoogleAuthButton from '../../../shared/components/ui/GoogleAuthButton.jsx';
import Input from '../../../shared/components/ui/Input.jsx';
import PasswordInput from '../../../shared/components/ui/PasswordInput.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { useSignupMutation } from '../hooks/useSignupMutation.js';
import { useGoogleAuthMutation } from '../hooks/useGoogleAuthMutation.js';
import { getAuthErrorTranslationKey } from '../utils/authErrors.js';
import { firstValidationError, validateConfirmPassword, validateEmail, validatePassword, validateRequired } from '../validation/authValidation.js';
import { AuthPanel } from '../components/AuthPanel.jsx';
import { AuthStatusMessage } from '../components/AuthStatusMessage.jsx';
import { PasswordRequirements } from '../components/PasswordRequirements.jsx';
import '../styles/AuthForms.css';

export function SignupPage() {
  const { locale, t } = useI18n();
  const location = useLocation();
  const navigate = useNavigate();
  const [values, setValues] = useState({ name: '', business: '', email: location.state?.email || '', password: '', confirmPassword: '', acceptedTerms: false });
  const [errors, setErrors] = useState({});
  const [touched, setTouched] = useState({});
  const [passwordFocused, setPasswordFocused] = useState(false);
  const [requestError, setRequestError] = useState('');
  const translateError = (validation) => {
    const validationError = firstValidationError(validation);
    return validationError ? t(validationError.key, validationError.params) : '';
  };

  const validateField = (name, nextValues) => ({
    name: () => translateError(validateRequired(nextValues.name, { messageKey: 'auth.validation.fullNameRequired' })),
    business: () => translateError(validateRequired(nextValues.business, { messageKey: 'auth.validation.businessNameRequired' })),
    email: () => translateError(validateEmail(nextValues.email)),
    password: () => translateError(validatePassword(nextValues.password)),
    confirmPassword: () => translateError(validateConfirmPassword(nextValues.password, nextValues.confirmPassword)),
    acceptedTerms: () => nextValues.acceptedTerms ? '' : t('auth.validation.termsRequired'),
  }[name]());

  const signupMutation = useSignupMutation({
    onSuccess: () => navigate(routePaths.verifyEmail, { state: { email: values.email } }),
    onError: (error) => setRequestError(getAuthErrorTranslationKey(error)),
  });
  const googleMutation = useGoogleAuthMutation({
    onSuccess: (response) => {
      if (response?.mock) setRequestError('auth.errors.authenticationUnavailable');
    },
    onError: (error) => setRequestError(getAuthErrorTranslationKey(error)),
  });

  React.useEffect(() => {
    const touchedFields = Object.keys(touched).filter((field) => touched[field]);
    if (!touchedFields.length) return;
    setErrors((current) => ({
      ...current,
      ...Object.fromEntries(touchedFields.map((field) => [field, validateField(field, values)])),
    }));
  }, [locale]);

  const update = (name) => (event) => {
    const value = event.target.type === 'checkbox' ? event.target.checked : event.target.value;
    const nextValues = { ...values, [name]: value };
    setValues(nextValues);
    setRequestError('');

    const shouldValidate = touched[name] || errors[name] || (name === 'confirmPassword' && value.length > 0);
    if (shouldValidate) {
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

  const submit = (event) => {
    event.preventDefault();
    const fields = ['name', 'business', 'email', 'password', 'confirmPassword', 'acceptedTerms'];
    const nextErrors = Object.fromEntries(fields.map((field) => [field, validateField(field, values)]));
    setTouched(Object.fromEntries(fields.map((field) => [field, true])));
    setErrors(nextErrors);
    setRequestError('');
    if (Object.values(nextErrors).some(Boolean)) return;
    signupMutation.mutate(values);
  };

  return (
    <AuthPanel title={t('auth.signup.title')} subtitle={t('auth.signup.subtitle')}>
      <AuthStatusMessage>{requestError ? t(requestError) : ''}</AuthStatusMessage>
      <GoogleAuthButton onClick={() => { setRequestError(''); googleMutation.mutate({ intent: 'signup' }); }} disabled={signupMutation.isPending} loading={googleMutation.isPending} loadingLabel={t('auth.loading.signup')}>{t('auth.signup.google')}</GoogleAuthButton>
      <div className="ceopro-auth-divider"><span>{t('auth.common.orContinueWithEmail')}</span></div>
      <form className="ceopro-auth-form" onSubmit={submit} noValidate>
        <div className="ceopro-auth-split-fields">
          <Input label={t('auth.common.fullName')} autoComplete="name" placeholder={t('auth.signup.namePlaceholder')} value={values.name} error={errors.name} onChange={update('name')} onBlur={blurField('name')} disabled={signupMutation.isPending} />
          <Input label={t('auth.common.businessName')} autoComplete="organization" placeholder={t('auth.signup.businessPlaceholder')} value={values.business} error={errors.business} onChange={update('business')} onBlur={blurField('business')} disabled={signupMutation.isPending} />
        </div>
        <Input label={t('auth.common.email')} type="email" autoComplete="email" placeholder={t('auth.signup.emailPlaceholder')} value={values.email} error={errors.email} onChange={update('email')} onBlur={blurField('email')} disabled={signupMutation.isPending} />
        <PasswordInput label={t('auth.common.password')} showPasswordLabel={t('auth.common.showPassword')} hidePasswordLabel={t('auth.common.hidePassword')} autoComplete="new-password" placeholder={t('auth.signup.passwordPlaceholder')} value={values.password} error={errors.password} onChange={update('password')} onFocus={() => setPasswordFocused(true)} onBlur={() => { setPasswordFocused(false); blurField('password')(); }} disabled={signupMutation.isPending} />
        <PasswordRequirements password={values.password} visible={passwordFocused} />
        <PasswordInput label={t('auth.common.confirmPassword')} showPasswordLabel={t('auth.common.showPassword')} hidePasswordLabel={t('auth.common.hidePassword')} autoComplete="new-password" placeholder={t('auth.signup.confirmPasswordPlaceholder')} value={values.confirmPassword} error={errors.confirmPassword} onChange={update('confirmPassword')} onBlur={blurField('confirmPassword')} disabled={signupMutation.isPending} />
        <Checkbox className="ceopro-auth-terms" checked={values.acceptedTerms} error={errors.acceptedTerms} disabled={signupMutation.isPending} onChange={update('acceptedTerms')} onBlur={blurField('acceptedTerms')}>
          {t('auth.signup.agreementPrefix')} <a className="ceopro-auth-link" href="#terms">{t('auth.signup.terms')}</a> {t('auth.signup.and')} <a className="ceopro-auth-link" href="#privacy">{t('auth.signup.privacy')}</a>.
        </Checkbox>
        <Button type="submit" variant="primary" fullWidth loading={signupMutation.isPending} disabled={googleMutation.isPending} loadingLabel={t('auth.loading.signup')}>{t('auth.signup.submit')}</Button>
      </form>
      <div className="ceopro-auth-footer-row"><span>{t('auth.signup.hasAccount')}</span><Link className="ceopro-auth-link" to={routePaths.login}>{t('auth.signup.loginInstead')}</Link></div>
    </AuthPanel>
  );
}
