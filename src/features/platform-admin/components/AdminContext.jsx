import { createContext, useContext, useState, useCallback, useEffect } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { useAuthStore } from '../../auth/store/authStore.js';
import { platformAdminApi as api, ADMIN_PREVIEW } from '../api/platformAdminApi.js';
import { can, requirePermission, PLATFORM_ROLES } from '../permissions/platformPermissions.js';
import Button from '../../../shared/components/ui/Button.jsx';
import Toast from '../../../shared/components/ui/Toast.jsx';
import { ShieldCheck } from 'lucide-react';

const Context = createContext(null);
export function useAdminText() { const { t, ...rest } = useI18n(); return { ...rest, t: (key, values) => t(`platformAdmin.${key}`, values) }; }
export const useAdmin = () => useContext(Context);
export const roleDescriptions = { SUPER_ADMIN: 'superDescription', ADMIN: 'adminDescription', EDITOR: 'editorDescription', VIEWER: 'viewerDescription' };
export function AdminProvider({ children }) {
  const { t } = useAdminText(), auth = useAuthStore(), location = useLocation(), client = useQueryClient();
  const [previewRole, setRole] = useState(''), [notice, setNotice] = useState(null), [selecting, setSelecting] = useState(false);
  const query = useQuery({ queryKey: ['platform-admin', 'me', auth.user?.id || auth.user?.user_id || 'anonymous', previewRole], queryFn: api.me, enabled: auth.isHydrated && (ADMIN_PREVIEW || auth.status === 'authenticated'), retry: false, staleTime: 0 });
  const notify = useCallback((message, variant = 'success') => setNotice({ message, variant }), []);
  useEffect(() => { if (!notice) return; const timer = setTimeout(() => setNotice(null), 6500); return () => clearTimeout(timer); }, [notice]);
  const chooseRole = async value => { setSelecting(true); await api.setPreviewRole(value); client.removeQueries({ queryKey: ['platform-admin'], predicate: q => q.queryKey[1] !== 'me' }); setRole(value); await query.refetch(); setSelecting(false); };
  if (!auth.isHydrated) return <div className="pa-gate" role="status">{t('loading')}</div>;
  if (!ADMIN_PREVIEW && auth.status !== 'authenticated') return <Navigate to="/login" state={{ from: location }} replace />;
  if (query.isPending) return <div className="pa-gate" role="status">{t('loading')}</div>;
  if (query.isError) return <div className="pa-gate"><ShieldCheck size={36} /><h1>{t('forbiddenTitle')}</h1><p>{t(query.error?.response?.status === 403 ? 'forbidden' : 'missingContract')}</p><Button onClick={() => query.refetch()}>{t('retry')}</Button><a href="/dashboard">{t('customerApp')}</a></div>;
  if (!can(query.data)) return <div className="pa-gate"><ShieldCheck size={42} /><h1>{t(ADMIN_PREVIEW ? 'platform' : 'forbiddenTitle')}</h1><p>{t(ADMIN_PREVIEW ? 'previewIntro' : 'forbidden')}</p>{ADMIN_PREVIEW ? <><div className="pa-notice">{t('previewNote')}</div>{PLATFORM_ROLES.map(role => <Button disabled={selecting} key={role} onClick={() => chooseRole(role)}>{t(role)}</Button>)}</> : <a href="/dashboard">{t('customerApp')}</a>}</div>;
  const value = { principal: query.data, can: permission => can(query.data, permission), preview: ADMIN_PREVIEW, chooseRole, notify };
  return <Context.Provider value={value}>{children}{notice && <div className="pa-toast"><Toast message={notice.message} variant={notice.variant} /></div>}</Context.Provider>;
}
export function useAdminQuery(domain, params = {}, id) {
  const { principal } = useAdmin();
  return useQuery({ queryKey: ['platform-admin', principal.id, principal.role, domain, id || null, params], queryFn: ({ signal }) => id ? api.detail(domain, id, signal) : api.list(domain, params, signal), retry: false });
}
export function useAdminMutation(permission) {
  const { principal, notify, preview } = useAdmin(), { t } = useAdminText(), client = useQueryClient();
  return useMutation({ mutationFn: ({ domain, id, action, payload }) => { requirePermission(principal, permission); return domain === 'account' ? api.account(action, payload) : api.mutate(domain, id, action, payload); }, onSuccess: () => { client.invalidateQueries({ queryKey: ['platform-admin'] }); client.invalidateQueries({ queryKey: ['plans'] }); notify(t(preview ? 'previewSaved' : 'saved')); }, onError: error => notify(t(['invalid', 'duplicate', 'conflict', 'lastAdmin', 'forbidden', 'notFound'].includes(error.code) ? error.code : 'failed'), 'error') });
}
