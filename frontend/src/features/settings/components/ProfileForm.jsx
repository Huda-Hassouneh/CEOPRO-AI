import { useEffect, useMemo, useState } from 'react';
import Avatar from '../../../shared/components/ui/Avatar.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import Input from '../../../shared/components/ui/Input.jsx';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import { SettingsSection } from './SettingsSection.jsx';
import { useUpdateProfile } from '../hooks/useUpdateProfile.js';

export default function ProfileForm({ query, t, onNotice }) {
  const profile = query.data?.profile;
  const [values, setValues] = useState({ fullName: '', jobTitle: '' });
  const mutation = useUpdateProfile();
  useEffect(() => { if (profile) setValues({ fullName: profile.fullName || '', jobTitle: profile.jobTitle || '' }); }, [profile]);
  const dirty = Boolean(profile) && (values.fullName !== (profile.fullName || '') || values.jobTitle !== (profile.jobTitle || ''));
  const initials = useMemo(() => values.fullName.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join('').toUpperCase(), [values.fullName]);

  if (query.isPending) return <Skeleton height="320px" variant="rectangular" />;
  if (query.isError) return <SettingsSection title={t('settings.profile.title')}><p className="settings-inline-error">{t('settings.profile.loadError')}</p></SettingsSection>;

  const save = async (event) => {
    event.preventDefault();
    if (!query.data.capabilities.updateProfile || mutation.isPending || !dirty || !values.fullName.trim()) return;
    try {
      const result = await mutation.mutateAsync(values);
      onNotice(result.persisted ? 'success' : 'info', t(result.persisted ? 'settings.profile.saved' : 'settings.profile.unavailable'));
    } catch {
      onNotice('error', t('settings.profile.saveError'));
    }
  };
  return <SettingsSection title={t('settings.profile.title')} subtitle={t('settings.profile.subtitle')}><form className="settings-form" onSubmit={save}>
    <div className="settings-profile-identity"><Avatar src={profile.avatarUrl} alt={values.fullName || t('settings.profile.avatar')} fallback={initials} size="64px" /><div><strong>{values.fullName || t('settings.common.notAvailable')}</strong><span>{profile.email || t('settings.common.notAvailable')}</span>{!query.data.capabilities.avatarUpload && <small>{t('settings.profile.avatarUnavailable')}</small>}</div></div>
    <div className="settings-form-grid"><Input label={t('settings.profile.fullName')} value={values.fullName} readOnly={!query.data.capabilities.updateProfile} onChange={(event) => setValues({ ...values, fullName: event.target.value })} /><Input label={t('settings.profile.email')} value={profile.email || ''} readOnly hint={t('settings.profile.emailReadOnly')} />{profile.jobTitle && <Input label={t('settings.profile.jobTitle')} readOnly={!query.data.capabilities.updateProfile} value={values.jobTitle} onChange={(event) => setValues({ ...values, jobTitle: event.target.value })} />}</div>
    {!query.data.capabilities.updateProfile && <p className="settings-capability-note">{t('settings.profile.unavailable')}</p>}<div className="settings-form-actions"><Button type="submit" disabled={!query.data.capabilities.updateProfile || !dirty || !values.fullName.trim()} loading={mutation.isPending} loadingLabel={t('settings.common.saving')}>{t('settings.common.saveChanges')}</Button></div>
  </form></SettingsSection>;
}
