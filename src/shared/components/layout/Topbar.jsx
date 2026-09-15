import { useState } from 'react';
import { Bell, Languages, Menu, Search, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { useAuthStore } from '../../../features/auth/store/authStore.js';
import Avatar from '../ui/Avatar.jsx';
import { getAccountProfile } from '../../../features/onboarding/utils/accountProfile.js';

export default function Topbar({ onMenuClick }) {
  const { t, dir, locale, setLocale } = useI18n();
  const user = useAuthStore((state) => state.user);
  const clearSession = useAuthStore((state) => state.clearSession);
  const navigate = useNavigate();
  const profile = getAccountProfile(user, t);
  const displayProfile = import.meta.env.DEV && import.meta.env.VITE_ENABLE_AUTH_PREVIEW === 'true' && !user
    ? { ...profile, personName: 'Preview User', companyName: 'Local development preview', email: 'preview@localhost', initials: 'PV' }
    : profile;
  const [query, setQuery] = useState('');
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);

  return <header className="business-topbar" dir={dir}>
    <button type="button" className="business-topbar__menu" onClick={onMenuClick} aria-label={t('businessShell.mobile.openMenu')}><Menu size={20} aria-hidden="true" /></button>
    <div className="business-topbar__search">
      <Search size={17} aria-hidden="true" />
      <label className="sr-only" htmlFor="business-global-search">{t('businessShell.search.label')}</label>
      <input id="business-global-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('businessShell.search.placeholder')} type="search" />
      {query && <button type="button" onClick={() => setQuery('')} aria-label={t('businessShell.search.clear')}><X size={15} /></button>}
    </div>
    <div className="business-topbar__actions">
      <button type="button" className="business-topbar__language" onClick={() => setLocale(locale === 'en' ? 'ar' : 'en')} aria-label={t('common.languageSwitch')}><Languages size={17} aria-hidden="true" /><span>{locale === 'en' ? t('common.arabicShort') : t('common.englishShort')}</span></button>
      <button type="button" className="business-topbar__icon-button" aria-label={t('businessShell.notifications.label')} aria-expanded={notificationsOpen} onClick={() => setNotificationsOpen((open) => !open)}><Bell size={18} aria-hidden="true" /><span className="business-topbar__unread" aria-label={t('businessShell.notifications.unread')} /></button>
      <button type="button" className="business-topbar__profile" aria-label={t('businessShell.profile.label')} aria-expanded={profileOpen} onClick={() => setProfileOpen((open) => !open)}>
        <Avatar src={displayProfile.avatarUrl} alt={displayProfile.personName} fallback={displayProfile.initials} size="34px" />
        <span className="business-topbar__profile-copy"><small>{t('businessShell.profile.welcome')}</small><strong>{displayProfile.personName}</strong></span>
        <span className="business-topbar__chevron" aria-hidden="true">⌄</span>
      </button>
      {notificationsOpen && <div className="business-topbar__notification-preview" role="status">{t('businessShell.notifications.preview')}</div>}
      {profileOpen && <div className="business-topbar__profile-menu" role="menu"><strong>{displayProfile.personName}</strong><span>{displayProfile.email}</span><span>{displayProfile.companyName}</span><button type="button" role="menuitem" onClick={() => { clearSession(); navigate('/login', { replace: true }); }}>{t('businessShell.navigation.logout')}</button></div>}
    </div>
  </header>;
}
