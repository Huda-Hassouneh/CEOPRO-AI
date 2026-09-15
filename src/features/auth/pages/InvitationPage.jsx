import React from 'react';
import { AlertCircle, Building2, Clock3, UserRound } from 'lucide-react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import Button from '../../../shared/components/ui/Button.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { useAcceptInvitationMutation, useInvitationQuery } from '../hooks/useInvitation.js';
import { getInvitationPreview } from '../mocks/authPreviewData.js';
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
  const token = searchParams.get('token') || '';
  const previewState = searchParams.get('state') === 'expired' ? 'expired' : 'active';
  const invitationQuery = useInvitationQuery(token);
  const invitation = invitationQuery.data?.invitation || getInvitationPreview(previewState);
  const [requestMessage, setRequestMessage] = React.useState(null);
  const acceptMutation = useAcceptInvitationMutation({
    onSuccess: () => setRequestMessage({ tone: 'success', key: 'auth.success.invitationAccepted' }),
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
          <strong>{invitation.organizationName}</strong>
          <p>{t('auth.invitation.joinTeam')}</p>
        </div>
      </div>
      <div className="ceopro-invitation-meta" aria-label={t('auth.invitation.detailsLabel')}>
        <div className="ceopro-invitation-meta__item">
          <UserRound size={19} aria-hidden="true" />
          <span>{t('auth.invitation.invitedBy')}<strong>{invitation.inviterName}</strong></span>
        </div>
        <div className="ceopro-invitation-meta__divider" aria-hidden="true" />
        <div className="ceopro-invitation-meta__item">
          <Clock3 size={19} aria-hidden="true" />
          <span>{t('auth.invitation.expiresIn')}<strong>{t('auth.invitation.days', { count: invitation.expiresInDays })}</strong></span>
        </div>
      </div>
      <div className="ceopro-invitation-actions">
        <Button
          variant="primary"
          fullWidth
          loading={acceptMutation.isPending}
          loadingLabel={t('auth.loading.acceptingInvitation')}
          disabled={invitationQuery.isLoading}
          onClick={() => { setRequestMessage(null); acceptMutation.mutate({ token }); }}
        >
          {t('auth.invitation.accept')}
        </Button>
        <Button variant="outline" fullWidth disabled={acceptMutation.isPending} onClick={goToLogin}>
          {t('auth.invitation.anotherAccount')}
        </Button>
      </div>
      <p className="ceopro-invitation-footer">
        {t('auth.invitation.wrongAccount')}{' '}
        <button type="button" className="ceopro-auth-link ceopro-auth-text-button" onClick={goToLogin}>
          {t('auth.invitation.differentEmail')}
        </button>
      </p>
    </AuthPanel>
  );
}
