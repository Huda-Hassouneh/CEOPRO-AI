import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useAuthStore, selectIsAuthenticated } from '../auth/store/authStore.js';
import { useI18n } from '../../app/providers/I18nProvider.jsx';
import { platformApi } from './platformApi.js';
export function PlatformAccessLink() {
  const authenticated = useAuthStore(selectIsAuthenticated); const { t } = useI18n();
  const userId = useAuthStore((s) => s.user?.id);
  const who = useQuery({ queryKey: ['platform', userId, 'me'], queryFn: platformApi.me, enabled: authenticated, retry: false });
  return who.data ? <Link to="/platform">{t('platform.title')}</Link> : null;
}
