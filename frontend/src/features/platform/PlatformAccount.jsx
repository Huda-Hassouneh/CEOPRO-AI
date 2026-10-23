import { useState } from 'react';
import { useI18n } from '../../app/providers/I18nProvider.jsx';
import { useAuthStore } from '../auth/store/authStore.js';
import { useProfile } from '../settings/hooks/useProfile.js';
import ProfileForm from '../settings/components/ProfileForm.jsx';
import { SecuritySettings } from '../settings/components/SecuritySettings.jsx';
import '../settings/styles/Settings.css';

// Existing Python profile/password/session capabilities, without customer plan/setup gates.
export function PlatformAccount() {
  const { t } = useI18n(); const user = useAuthStore((s) => s.user);
  const profile = useProfile(user); const [notice, setNotice] = useState('');
  const onNotice = (_variant, message) => setNotice(message);
  return <section>{notice && <p role="status">{notice}</p>}<ProfileForm query={profile} t={t} onNotice={onNotice} /><SecuritySettings t={t} onNotice={onNotice} /></section>;
}
