import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ShieldCheck } from 'lucide-react';
import { useAuthStore, selectIsAuthenticated } from '../auth/store/authStore.js';
import { useI18n } from '../../app/providers/I18nProvider.jsx';
import { platformApi } from './platformApi.js';

// Shown only to platform staff (GET /platform/me answers them alone), as an
// item in the profile menu.
export function PlatformAccessLink({ onNavigate }) {
  const authenticated = useAuthStore(selectIsAuthenticated); const { t } = useI18n();
  const userId = useAuthStore((s) => s.user?.id);
  const who = useQuery({ queryKey: ['platform', userId, 'me'], queryFn: platformApi.me, enabled: authenticated, retry: false });
  return who.data ? <Link to="/platform" role="menuitem" className="apex-topnav__menu-link" onClick={onNavigate}><ShieldCheck size={15} aria-hidden="true" />{t('platform.title')}</Link> : null;
}
