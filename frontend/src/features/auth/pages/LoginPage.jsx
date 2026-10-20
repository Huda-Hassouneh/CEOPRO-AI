import React, { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Building2, ChevronRight, LockKeyhole, Mail } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';
import Input from '../../../shared/components/ui/Input.jsx';
import PasswordInput from '../../../shared/components/ui/PasswordInput.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { useAuthStore } from '../store/authStore.js';
import { useLoginMutation } from '../hooks/useLoginMutation.js';
import { getPostLoginDestination } from '../utils/authRouting.js';
import { getAuthErrorTranslationKey } from '../utils/authErrors.js';
import { firstValidationError, validateEmail, validateRequired } from '../validation/authValidation.js';
import { AuthPanel } from '../components/AuthPanel.jsx';
import { AuthStatusMessage } from '../components/AuthStatusMessage.jsx';
import '../styles/AuthForms.css';

export function LoginPage() {
  const { locale, t } = useI18n();
  const location = useLocation();
  const navigate = useNavigate();
  const setSession = useAuthStore((state) => state.setSession);
  const [values, setValues] = useState({ email: '', password: '' });
  const [errors, setErrors] = useState({});
  const [workspaces, setWorkspaces] = useState(null);
  const [touched, setTouched] = useState({});
  const [requestMessage, setRequestMessage] = useState(
    {
      'logout-unconfirmed': { tone: 'error', key: 'auth.success.logoutUnconfirmed' },
      'password-reset': { tone: 'success', key: 'auth.success.passwordReset' },
      'company-deleted': { tone: 'success', key: 'auth.success.companyDeleted' },
      'email-verified': { tone: 'success', key: 'auth.success.emailVerified' },
    }[location.state?.authNotice] || null,
  );

  const translateError = (validation) => {
    const validationError = firstValidationError(validation);
    return validationError ? t(validationError.key, validationError.params) : '';
  };

  const validateField = (name, value) => name === 'email'
    ? translateError(validateEmail(value))
    : translateError(validateRequired(value, { messageKey: 'auth.validation.passwordRequired' }));

  const loginMutation = useLoginMutation({
    onSuccess: (response) => {
      if (!response?.session) {
        setRequestMessage({ tone: 'error', key: 'auth.errors.authenticationUnavailable' });
        return;
      }
      setSession(response.session);
      navigate(getPostLoginDestination(location.state), { replace: true });
    },
    onError: (error) => {
      // One login can own several companies: the server lists them and
      // asks which one to open.
      const choices = error?.response?.status === 409 ? error.response.data?.detail?.workspaces : null;
      if (Array.isArray(choices) && choices.length) {
        setWorkspaces(choices);
        return;
      }
      setRequestMessage({
        tone: 'error',
        key: getAuthErrorTranslationKey(error, { unauthorizedKey: 'auth.errors.invalidCredentials' }),
      });
    },
  });
  React.useEffect(() => {
    setErrors((current) => ({
      ...current,
      ...(touched.email ? { email: validateField('email', values.email) } : {}),
      ...(touched.password ? { password: validateField('password', values.password) } : {}),
    }));
  // Re-translate visible errors when the language changes only; typing re-validates on its own.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locale]);

  const updateField = (name) => (event) => {
    const value = event.target.value;
    setValues((current) => ({ ...current, [name]: value }));
    setRequestMessage(null);
    if (touched[name] || errors[name]) {
      setErrors((current) => ({ ...current, [name]: validateField(name, value) }));
    }
  };

  const blurField = (name) => () => {
    setTouched((current) => ({ ...current, [name]: true }));
    setErrors((current) => ({ ...current, [name]: validateField(name, values[name]) }));
  };

  const submit = (event) => {
    event.preventDefault();
    const nextErrors = {
      email: validateField('email', values.email),
      password: validateField('password', values.password),
    };
    setTouched({ email: true, password: true });
    setErrors(nextErrors);
    setRequestMessage(null);
    if (nextErrors.email || nextErrors.password) return;
    loginMutation.mutate(values);
  };

  if (workspaces) {
    return (
      <AuthPanel title={t('auth.workspaces.title')} subtitle={t('auth.workspaces.subtitle')} className="ceopro-auth-body--narrow">
        <AuthStatusMessage tone={requestMessage?.tone}>{requestMessage?.key ? t(requestMessage.key) : ''}</AuthStatusMessage>
        <ul className="auth-workspaces">
          {workspaces.map((workspace) => (
            <li key={workspace.tenant_id}>
              <button type="button" disabled={loginMutation.isPending} onClick={() => loginMutation.mutate({ ...values, tenant_id: workspace.tenant_id })}>
                <Building2 size={18} aria-hidden="true" />
                <span><strong>{workspace.business_name}</strong><small>{t(`settings.roles.${workspace.role_key}.label`)}</small></span>
                <ChevronRight size={16} aria-hidden="true" className="auth-workspaces__chevron" />
              </button>
            </li>
          ))}
        </ul>
        <button type="button" className="ceopro-auth-link ceopro-auth-link--secondary" onClick={() => setWorkspaces(null)}>{t('auth.workspaces.back')}</button>
      </AuthPanel>
    );
  }

  return (
    <AuthPanel title={t('auth.login.title')} subtitle={t('auth.login.subtitle')} className="ceopro-auth-body--narrow">
      <AuthStatusMessage tone={requestMessage?.tone}>{requestMessage?.key ? t(requestMessage.key) : ''}</AuthStatusMessage>
      <form className="ceopro-auth-form" onSubmit={submit} noValidate>
        <Input label={t('auth.common.emailAddress')} type="email" autoComplete="email" placeholder={t('auth.login.emailPlaceholder')} leftIcon={<Mail size={25} />} value={values.email} error={errors.email} onChange={updateField('email')} onBlur={blurField('email')} disabled={loginMutation.isPending} />
        <PasswordInput label={t('auth.common.password')} showPasswordLabel={t('auth.common.showPassword')} hidePasswordLabel={t('auth.common.hidePassword')} autoComplete="current-password" placeholder={t('auth.login.passwordPlaceholder')} leftIcon={<LockKeyhole size={24} />} value={values.password} error={errors.password} onChange={updateField('password')} onBlur={blurField('password')} disabled={loginMutation.isPending} />
        <div className="ceopro-auth-inline-row">
          <Link className="ceopro-auth-link ceopro-auth-link--secondary" to={routePaths.forgotPassword}>{t('auth.login.forgotPassword')}</Link>
        </div>
        <Button type="submit" variant="primary" fullWidth loading={loginMutation.isPending} loadingLabel={t('auth.loading.login')}>{t('auth.login.submit')}</Button>
      </form>
      <div className="ceopro-auth-footer-row"><span>{t('auth.login.noAccount')}</span><Link className="ceopro-auth-link" to={routePaths.signup}>{t('auth.login.signup')}</Link></div>
    </AuthPanel>
  );
}
