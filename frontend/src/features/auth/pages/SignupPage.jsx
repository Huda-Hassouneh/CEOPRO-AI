import React, { useState } from 'react';
import { savePendingRegistration } from '../pendingRegistration.js';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import Button from '../../../shared/components/ui/Button.jsx';
import Checkbox from '../../../shared/components/ui/Checkbox.jsx';
import Input from '../../../shared/components/ui/Input.jsx';
import PasswordInput from '../../../shared/components/ui/PasswordInput.jsx';
import Select from '../../../shared/components/ui/Select.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { useAuthStore } from '../store/authStore.js';
import { useSignupMutation } from '../hooks/useSignupMutation.js';
import { getAuthErrorTranslationKey } from '../utils/authErrors.js';
import { firstValidationError, validateConfirmPassword, validateCurrency, validateEmail, validatePassword, validateRequired } from '../validation/authValidation.js';
import { countryOptions, currencyOptions, defaultCurrencyFor } from '../../../shared/config/countries.js';
import { AuthPanel } from '../components/AuthPanel.jsx';
import { AuthStatusMessage } from '../components/AuthStatusMessage.jsx';
import { PasswordRequirements } from '../components/PasswordRequirements.jsx';
import '../styles/AuthForms.css';

export function SignupPage() {
  const { locale, t } = useI18n();
  const location = useLocation();
  const navigate = useNavigate();
  const setSession = useAuthStore((state) => state.setSession);
  const [values, setValues] = useState({ name: '', business: '', email: location.state?.email || '', password: '', confirmPassword: '', country: '', currency: '', acceptedTerms: false });
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
    country: () => translateError(validateRequired(nextValues.country, { messageKey: 'auth.validation.countryRequired' })),
    currency: () => translateError(validateCurrency(nextValues.currency)),
    acceptedTerms: () => nextValues.acceptedTerms ? '' : t('auth.validation.termsRequired'),
  }[name]());

  const signupMutation = useSignupMutation({
    onSuccess: (response) => {
      if (response?.session) setSession(response.session);
      if (response?.pendingRegistration) savePendingRegistration(response.pendingRegistration);
      navigate(routePaths.verifyEmail, { state: { email: values.email } });
    },
    onError: (error) => setRequestError(getAuthErrorTranslationKey(error, { fallbackKey: error?.response?.status === 409 ? 'auth.errors.emailInUse' : 'auth.errors.generic' })),
  });

  React.useEffect(() => {
    const touchedFields = Object.keys(touched).filter((field) => touched[field]);
    if (!touchedFields.length) return;
    setErrors((current) => ({
      ...current,
      ...Object.fromEntries(touchedFields.map((field) => [field, validateField(field, values)])),
    }));
  // Re-translate visible errors when the language changes only; typing re-validates on its own.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locale]);

  const update = (name) => (event) => {
    const value = event.target.type === 'checkbox' ? event.target.checked : event.target.value;
    const nextValues = { ...values, [name]: value };
    // Picking a country fills in its usual currency unless one was chosen.
    if (name === 'country' && (!values.currency || values.currency === defaultCurrencyFor(values.country))) {
      nextValues.currency = value ? defaultCurrencyFor(value) : '';
    }
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
    const fields = ['name', 'business', 'email', 'password', 'confirmPassword', 'country', 'currency', 'acceptedTerms'];
    const nextErrors = Object.fromEntries(fields.map((field) => [field, validateField(field, values)]));
    setTouched(Object.fromEntries(fields.map((field) => [field, true])));
    setErrors(nextErrors);
    setRequestError('');
    if (Object.values(nextErrors).some(Boolean)) return;
    signupMutation.mutate({ ...values, currency: values.currency.trim().toUpperCase() });
  };

  return (
    <AuthPanel title={t('auth.signup.title')} subtitle={t('auth.signup.subtitle')}>
      <AuthStatusMessage>{requestError ? t(requestError) : ''}</AuthStatusMessage>
      <form className="ceopro-auth-form" onSubmit={submit} noValidate>
        <div className="ceopro-auth-split-fields">
          <Input label={t('auth.common.fullName')} autoComplete="name" placeholder={t('auth.signup.namePlaceholder')} value={values.name} error={errors.name} onChange={update('name')} onBlur={blurField('name')} disabled={signupMutation.isPending} />
          <Input label={t('auth.common.businessName')} autoComplete="organization" placeholder={t('auth.signup.businessPlaceholder')} value={values.business} error={errors.business} onChange={update('business')} onBlur={blurField('business')} disabled={signupMutation.isPending} />
        </div>
        <Input label={t('auth.common.email')} type="email" autoComplete="email" placeholder={t('auth.signup.emailPlaceholder')} value={values.email} error={errors.email} onChange={update('email')} onBlur={blurField('email')} disabled={signupMutation.isPending} />
        <div className="ceopro-auth-split-fields">
          <Select
            label={t('auth.common.country')}
            value={values.country}
            error={errors.country}
            onChange={update('country')}
            onBlur={blurField('country')}
            disabled={signupMutation.isPending}
            options={[{ value: '', label: t('auth.signup.countryPlaceholder') }, ...countryOptions(locale)]}
          />
          <Select label={t('auth.common.currency')} value={values.currency} error={errors.currency} hint={t('auth.signup.currencyHint')} onChange={update('currency')} onBlur={blurField('currency')} disabled={signupMutation.isPending}
            options={[{ value: '', label: t('auth.signup.currencyPlaceholder') }, ...currencyOptions(locale)]}
          />
        </div>
        <PasswordInput label={t('auth.common.password')} showPasswordLabel={t('auth.common.showPassword')} hidePasswordLabel={t('auth.common.hidePassword')} autoComplete="new-password" placeholder={t('auth.signup.passwordPlaceholder')} value={values.password} error={errors.password} onChange={update('password')} onFocus={() => setPasswordFocused(true)} onBlur={() => { setPasswordFocused(false); blurField('password')(); }} disabled={signupMutation.isPending} />
        <PasswordRequirements password={values.password} visible={passwordFocused} />
        <PasswordInput label={t('auth.common.confirmPassword')} showPasswordLabel={t('auth.common.showPassword')} hidePasswordLabel={t('auth.common.hidePassword')} autoComplete="new-password" placeholder={t('auth.signup.confirmPasswordPlaceholder')} value={values.confirmPassword} error={errors.confirmPassword} onChange={update('confirmPassword')} onBlur={blurField('confirmPassword')} disabled={signupMutation.isPending} />
        <Checkbox className="ceopro-auth-terms" checked={values.acceptedTerms} error={errors.acceptedTerms} disabled={signupMutation.isPending} onChange={update('acceptedTerms')} onBlur={blurField('acceptedTerms')}>
          {t('auth.signup.agreementPrefix')} <a className="ceopro-auth-link" href={routePaths.terms} target="_blank" rel="noreferrer">{t('auth.signup.terms')}</a> {t('auth.signup.and')} <a className="ceopro-auth-link" href={routePaths.privacy} target="_blank" rel="noreferrer">{t('auth.signup.privacy')}</a>.
        </Checkbox>
        <Button type="submit" variant="primary" fullWidth loading={signupMutation.isPending} loadingLabel={t('auth.loading.signup')}>{t('auth.signup.submit')}</Button>
      </form>
      <div className="ceopro-auth-footer-row"><span>{t('auth.signup.hasAccount')}</span><Link className="ceopro-auth-link" to={routePaths.login}>{t('auth.signup.loginInstead')}</Link></div>
    </AuthPanel>
  );
}
