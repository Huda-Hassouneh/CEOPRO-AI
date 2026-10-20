import React from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useI18n } from '../../app/providers/I18nProvider.jsx';
import { useAuthStore } from '../auth/store/authStore.js';
import { toSession } from '../auth/api/authHttpAdapter.js';
import { AuthPanel } from '../auth/components/AuthPanel.jsx';
import Input from '../../shared/components/ui/Input.jsx';
import PasswordInput from '../../shared/components/ui/PasswordInput.jsx';
import Button from '../../shared/components/ui/Button.jsx';
import { platformApi as api, platformInvitationErrorKey } from './platformApi.js';

export function PlatformInvitation() {
  const { token } = useParams(); const { t } = useI18n(); const navigate = useNavigate();
  const invitation = useQuery({ queryKey: ['platform-invitation', token], queryFn: () => api.invitation(token), retry: false });
  const [name, setName] = React.useState(''); const [password, setPassword] = React.useState('');
  const [error, setError] = React.useState(''); const [busy, setBusy] = React.useState(false);
  const submit = async (event) => {
    event.preventDefault(); setBusy(true); setError('');
    try { const result = await api.accept(token, { ...(name ? { full_name: name } : {}), ...(password ? { password } : {}) }); useAuthStore.getState().setSession(toSession(result)); navigate('/platform', { replace: true }); }
    catch (failure) { setError(t(platformInvitationErrorKey(failure))); }
    finally { setBusy(false); }
  };
  return <AuthPanel title={t('platform.inviteTitle')} subtitle={invitation.data?.email || ''}>
    {invitation.isPending && <p role="status">{t('common.loading')}</p>}
    {(invitation.error || error) && <p role="alert">{error || t(platformInvitationErrorKey(invitation.error))}</p>}
    {invitation.data && <form onSubmit={submit}><p>{t('platform.inviteExplanation')}</p><Input label={t('auth.common.fullName')} autoComplete="name" maxLength={150} value={name} onChange={(e) => setName(e.target.value)} /><PasswordInput label={t('auth.common.password')} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} /><Button type="submit" loading={busy}>{t('platform.accept')}</Button></form>}
    <Link to="/login">{t('platform.backToLogin')}</Link>
  </AuthPanel>;
}
