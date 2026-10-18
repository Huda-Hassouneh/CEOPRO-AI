import { settingsCapabilities } from '../api/settingsCapabilities.js';
import { useState } from 'react';
import { KeyRound } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';
import PasswordInput from '../../../shared/components/ui/PasswordInput.jsx';
import { PasswordRequirements } from '../../auth/components/PasswordRequirements.jsx';
import { firstValidationError, validateConfirmPassword, validatePassword, validateRequired } from '../../auth/validation/authValidation.js';
import { useActiveSessions } from '../hooks/useActiveSessions.js';
import { useChangePassword } from '../hooks/useChangePassword.js';
import ActiveSessionsList from './ActiveSessionsList.jsx';
import { SettingsSection } from './SettingsSection.jsx';

export function SecuritySettings({ t, onNotice }) {
  const [values, setValues] = useState({ currentPassword: '', newPassword: '', confirmPassword: '' });
  const [errors, setErrors] = useState({});
  const [newFocused, setNewFocused] = useState(false);
  const mutation = useChangePassword();
  const sessionsQuery = useActiveSessions();
  const translateError = (result) => { const item = firstValidationError(result); return item ? t(item.key, item.params) : ''; };
  const submit = async (event) => {
    event.preventDefault();
    if (!settingsCapabilities.changePassword || mutation.isPending) return;
    const nextErrors = {
      currentPassword: translateError(validateRequired(values.currentPassword, { messageKey: 'settings.security.currentRequired' })),
      newPassword: translateError(validatePassword(values.newPassword)),
      confirmPassword: translateError(validateConfirmPassword(values.newPassword, values.confirmPassword)),
    };
    setErrors(nextErrors);
    if (Object.values(nextErrors).some(Boolean)) return;
    try {
      const result = await mutation.mutateAsync(values);
      if (!result.changed) return onNotice('info', t('settings.security.passwordUnavailable'));
      setValues({ currentPassword: '', newPassword: '', confirmPassword: '' });
      onNotice('success', t('settings.security.passwordChanged'));
    } catch { onNotice('error', t('settings.security.passwordFailed')); }
  };
  const update = (key) => (event) => { setValues({ ...values, [key]: event.target.value }); setErrors({ ...errors, [key]: '' }); };
  const passwordLabels = { showPasswordLabel: t('auth.common.showPassword'), hidePasswordLabel: t('auth.common.hidePassword') };
  return <div className="settings-security-stack"><SettingsSection title={t('settings.security.title')} subtitle={t('settings.security.subtitle')}>{!settingsCapabilities.changePassword && <p className="settings-capability-note">{t('settings.security.passwordUnavailable')}</p>}<form className="settings-password-form" onSubmit={submit}><span className="settings-security-icon"><KeyRound size={20} /></span><PasswordInput {...passwordLabels} label={t('settings.security.currentPassword')} autoComplete="current-password" value={values.currentPassword} error={errors.currentPassword} onChange={update('currentPassword')} disabled={!settingsCapabilities.changePassword || mutation.isPending} /><PasswordInput {...passwordLabels} label={t('settings.security.newPassword')} autoComplete="new-password" value={values.newPassword} error={errors.newPassword} onChange={update('newPassword')} onFocus={() => setNewFocused(true)} onBlur={() => setNewFocused(false)} disabled={!settingsCapabilities.changePassword || mutation.isPending} /><PasswordRequirements password={values.newPassword} visible={newFocused || Boolean(values.newPassword)} /><PasswordInput {...passwordLabels} label={t('settings.security.confirmPassword')} autoComplete="new-password" value={values.confirmPassword} error={errors.confirmPassword} onChange={update('confirmPassword')} disabled={!settingsCapabilities.changePassword || mutation.isPending} /><div className="settings-form-actions"><Button type="submit" disabled={!settingsCapabilities.changePassword} loading={mutation.isPending} loadingLabel={t('settings.security.changing')}>{t('settings.security.changePassword')}</Button></div></form></SettingsSection><SettingsSection title={t('settings.security.sessionsTitle')} subtitle={t('settings.security.sessionsSubtitle')}><ActiveSessionsList query={sessionsQuery} t={t} /></SettingsSection></div>;
}
