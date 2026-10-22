import React from 'react';
import { AlertCircle, Building2 } from 'lucide-react';
import { useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import Input from '../../../shared/components/ui/Input.jsx';
import PasswordInput from '../../../shared/components/ui/PasswordInput.jsx';
import { useAuthStore } from '../store/authStore.js';
import Button from '../../../shared/components/ui/Button.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { useAcceptInvitationMutation, useInvitationQuery } from '../hooks/useInvitation.js';
import { getAuthErrorTranslationKey } from '../utils/authErrors.js';
import { AuthPanel } from '../components/AuthPanel.jsx';
import { AuthStatusMessage } from '../components/AuthStatusMessage.jsx';
import '../styles/AuthForms.css';

const invitationImage = '/assets/images/invidedIma.png';

export function InvitationPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { t } = useI18n();
  const { token: pathToken } = useParams();
  const token = pathToken || searchParams.get('token') || '';
  const [fullName, setFullName] = React.useState('');
  const [password, setPassword] = React.useState('');
  const invitationQuery = useInvitationQuery(token);
  const invitation = invitationQuery.data || null;
  const [requestMessage, setRequestMessage] = React.useState(null);
  const acceptMutation = useAcceptInvitationMutation({
    onSuccess: (response) => {
      if (!response?.session?.accessToken) {
        setRequestMessage({ tone: 'error', key: 'auth.errors.authenticationUnavailable' });
        return;
      }
      useAuthStore.getState().setSession(response.session);
      navigate(routePaths.dashboard, { replace: true });
    },
    onError: (requestFailure) => setRequestMessage({ tone: 'error', key: getAuthErrorTranslationKey(requestFailure) }),
  });
  const goToLogin = () => navigate(routePaths.login, { state: { from: location } });

  if (token && invitationQuery.isPending) {
    return (
      <AuthPanel>
        <div className="ceopro-auth-inline-loading" role="status" aria-live="polite">
          {t('common.loading')}
        </div>
      </AuthPanel>
    );
  }

  // No real invitation to show - no token at all, or the backend couldn't
  // resolve the one provided. An honest "this link isn't valid" panel,
  // never a fabricated company/inviter card with a working Accept button.
  if (!invitation) {
    return (
      <AuthPanel className="ceopro-auth-notice">
        <div className="ceopro-invitation-expired-icon" aria-hidden="true"><AlertCircle /></div>
        <header className="ceopro-auth-header">
          <h1 className="ceopro-auth-title">{t('auth.invitation.invalidTitle')}</h1>
          <p className="ceopro-auth-subtitle">{t('auth.invitation.invalidBody')}</p>
        </header>
        <Button variant="outline" fullWidth onClick={goToLogin}>
          {t('auth.common.backToLogin')}
        </Button>
      </AuthPanel>
    );
  }

  if (invitation.status === 'expired') {
    return (
      <AuthPanel className="ceopro-auth-notice">
        <div className="ceopro-invitation-expired-icon" aria-hidden="true"><AlertCircle /></div>
        <header className="ceopro-auth-header">
          <h1 className="ceopro-auth-title">{t('auth.invitation.expiredTitle')}</h1>
          <p className="ceopro-auth-subtitle">{t('auth.invitation.expiredBody')}</p>
        </header>
        <Button variant="outline" fullWidth onClick={goToLogin}>
          {t('auth.common.backToLogin')}
        </Button>
      </AuthPanel>
    );
  }

  return (
    <AuthPanel>
      <img className="ceopro-invitation-image" src={invitationImage} alt={t('auth.invitation.imageAlt')} />
      <header className="ceopro-auth-header">
        <h1 className="ceopro-auth-title">{t('auth.invitation.title')}</h1>
        <p className="ceopro-auth-subtitle">{t('auth.invitation.subtitle')}</p>
      </header>
      <AuthStatusMessage>{invitationQuery.isError ? t('auth.errors.invitationUnavailable') : ''}</AuthStatusMessage>
      <AuthStatusMessage tone={requestMessage?.tone}>{requestMessage?.key ? t(requestMessage.key) : ''}</AuthStatusMessage>
      <div className="ceopro-invitation-summary">
        <div className="ceopro-invitation-summary__icon" aria-hidden="true"><Building2 /></div>
        <div>
          <strong>{invitation.business_name}</strong>
          <p>{t('auth.invitation.joinTeam')}</p>
        </div>
      </div>
      <p>{invitation.email} · {invitation.role_name}</p>
      <form onSubmit={(event) => {
        event.preventDefault();
        if (acceptMutation.isPending) return;
        setRequestMessage(null);
        acceptMutation.mutate({ token, ...(fullName.trim() ? { full_name: fullName.trim() } : {}), ...(password ? { password } : {}) });
      }}>
        <p>{t('auth.invitation.credentialsHelp')}</p>
        <Input label={t('auth.common.fullName')} autoComplete="name" maxLength={150} value={fullName} onChange={(event) => setFullName(event.target.value)} disabled={acceptMutation.isPending} />
        <PasswordInput label={t('auth.common.password')} autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} disabled={acceptMutation.isPending} />
        <div className="ceopro-invitation-actions">
          <Button
            variant="primary"
            fullWidth
            loading={acceptMutation.isPending}
            loadingLabel={t('auth.loading.acceptingInvitation')}
            disabled={invitationQuery.isLoading}
            type="submit"
          >
            {t('auth.invitation.accept')}
          </Button>
          <Button variant="outline" fullWidth disabled={acceptMutation.isPending} onClick={goToLogin}>
            {t('auth.invitation.anotherAccount')}
          </Button>
        </div>
      </form>
      <p className="ceopro-invitation-footer">
        {t('auth.invitation.wrongAccount')}{' '}
        <button type="button" className="ceopro-auth-link ceopro-auth-text-button" onClick={goToLogin}>
          {t('auth.invitation.differentEmail')}
        </button>
      </p>
    </AuthPanel>
  );
}
