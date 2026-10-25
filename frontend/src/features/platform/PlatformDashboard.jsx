import React from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuthStore, selectIsAuthenticated } from '../auth/store/authStore.js';
import { useI18n } from '../../app/providers/I18nProvider.jsx';
import Button from '../../shared/components/ui/Button.jsx';
import Input from '../../shared/components/ui/Input.jsx';
import { platformApi as api } from './platformApi.js';
import './platform.css';
import { PlatformAccount } from './PlatformAccount.jsx';
import { signOut } from '../../shared/components/layout/signOut.js';

const areas = ['overview', 'companies', 'users', 'team', 'audit', 'settings', 'approvals', 'account'];
export function PlatformDashboard() {
  const { t, locale } = useI18n(); const location = useLocation(); const navigate = useNavigate(); const queryClient = useQueryClient();
  const actor = useAuthStore((s) => s.user?.id);
  const hydrated = useAuthStore((s) => s.isHydrated); const authenticated = useAuthStore(selectIsAuthenticated);
  const [area, setArea] = React.useState('overview'); const [offset, setOffset] = React.useState(0); const [search, setSearch] = React.useState(''); const [settledSearch, setSettledSearch] = React.useState('');
  const [editor, setEditor] = React.useState(null); const [reason, setReason] = React.useState('');
  const [value, setValue] = React.useState(''); const [busy, setBusy] = React.useState(false);
  const [notice, setNotice] = React.useState(''); const [detail, setDetail] = React.useState(null);
  const [approval, setApproval] = React.useState({ kind: 'below_floor_price', subject: '', description: '', expires_at: '' });
  const requestId = React.useRef(null);
  const who = useQuery({ queryKey: ['platform', actor, 'me'], queryFn: api.me, enabled: hydrated && authenticated, retry: false });
  React.useEffect(() => {
    const timer = window.setTimeout(() => setSettledSearch(search.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [search]);
  const directorySearch = ['companies', 'users'].includes(area) ? settledSearch : undefined;
  const data = useQuery({ queryKey: ['platform', actor, area, offset, directorySearch], queryFn: () => api.read(area, offset, directorySearch), enabled: !!who.data && !['approvals', 'account'].includes(area), retry: false });
  if (!hydrated) return <p role="status">{t('common.loading')}</p>;
  if (!authenticated) return <Navigate to="/login" replace state={{ from: location }} />;
  const owner = who.data?.role === 'owner';
  const errorMessage = (error) => error?.response?.status === 403 ? t('platform.forbidden') : error?.response?.status === 409 ? t('platform.conflict') : t('platform.failed');
  const act = async (fn) => {
    setBusy(true); setNotice('');
    try { const result = await fn(); setEditor(null); setReason(''); setValue(''); setNotice(result?.delivery === 'unavailable' ? t('platform.deliveryFailed') : t('platform.saved')); await queryClient.invalidateQueries({ queryKey: ['platform'] }); return true; }
    catch (error) { setNotice(errorMessage(error)); return false; }
    finally { setBusy(false); }
  };
  const edit = (type, row) => { setEditor({ type, row }); setReason(''); setValue(row?.platform_notes || ''); setNotice(''); };
  const submit = (event) => {
    event.preventDefault(); if (!reason.trim()) return;
    const row = editor?.row;
    const handlers = {
      invite: () => api.invite({ email: value, reason }),
      metadata: () => api.company(row.tenant_id, { notes: value, reason }),
      companyStatus: () => api.companyStatus(row.tenant_id, { active: !!row.platform_suspended_at, reason }),
      membershipStatus: () => api.membershipStatus(row.tenant_user_id, { active: !!row.platform_suspended_at, reason }),
      userStatus: () => api.userStatus(row.user_id, { active: !!row.platform_disabled_at, reason }),
      suspendMember: () => api.member(row.user_id, { status: row.status === 'active' ? 'suspended' : 'active', reason }),
      removeMember: () => api.member(row.user_id, { status: 'removed', reason }),
      transfer: () => api.transfer(row.user_id, reason),
      resend: () => api.invitationAction(row.invitation_id, 'resend', reason),
      cancel: () => api.invitationAction(row.invitation_id, 'cancel', reason),
      settings: () => api.settings({ support_email: value, reason }),
    };
    if (handlers[editor?.type]) act(handlers[editor.type]);
  };
  const inspect = async (row) => { setNotice(''); try { setDetail(await api.detail(area, row.tenant_id || row.user_id)); } catch (error) { setNotice(errorMessage(error)); } };
  const items = data.data?.items || [];
  return <main className="keel-platform">
    <header><h1>{t('platform.title')}</h1><Link to="/dashboard">{t('platform.back')}</Link><Button variant="secondary" onClick={() => signOut(useAuthStore.getState().clearSession, navigate)}>{t('platform.signOut')}</Button></header>
    {who.error ? <section role="alert"><p>{errorMessage(who.error)}</p><Button onClick={() => who.refetch()}>{t('platform.retry')}</Button></section> : !who.data ? <p role="status">{t('common.loading')}</p> : <>
      <p>{t(owner ? 'platform.owner' : 'platform.admin')}</p>
      <nav aria-label={t('platform.title')}>{areas.filter((a) => a !== 'approvals' || owner).map((a) => <Button key={a} variant={a === area ? 'primary' : 'secondary'} onClick={() => { setArea(a); setOffset(0); setSearch(''); setSettledSearch(''); setDetail(null); setEditor(null); setNotice(''); }}>{t(`platform.${a}`)}</Button>)}{owner && <Button variant="secondary" onClick={() => navigate('/platform/billing')}>{locale === 'ar' ? 'الفوترة' : 'Billing'}</Button>}</nav>
      {notice && <p role="status">{notice}</p>}
      {data.error && area !== 'approvals' && <p role="alert">{errorMessage(data.error)} <Button onClick={() => data.refetch()}>{t('platform.retry')}</Button></p>}
      {!['approvals', 'account'].includes(area) && data.isPending ? <p role="status">{t('common.loading')}</p> : null}
      {area === 'account' && <PlatformAccount />}
      {area === 'overview' && data.data && <dl>{Object.entries(data.data).map(([k, v]) => <React.Fragment key={k}><dt>{t(`platform.${k}`)}</dt><dd>{v}</dd></React.Fragment>)}</dl>}
      {['companies', 'users'].includes(area) && <><Input label={t(area === 'companies' ? 'platform.searchCompanies' : 'platform.searchUsers')} value={search} onChange={(event) => { setSearch(event.target.value); setOffset(0); setDetail(null); }} />{(search.trim() !== settledSearch || data.isFetching) && <p role="status">{t('platform.searching')}</p>}{data.data && search.trim() === settledSearch && <p role="status">{t('platform.searchResultCount', { count: data.data.total })}</p>}<table><thead><tr><th>{t('platform.name')}</th><th>{t('platform.status')}</th><th>{t('platform.actions')}</th></tr></thead><tbody>{items.map((row) => <tr key={row.tenant_id || row.user_id}><td>{row.business_name || row.full_name}<br />{row.email || `${row.country_code} · ${row.primary_currency}`}</td><td>{t(row.platform_suspended_at || row.platform_disabled_at ? 'platform.suspended' : 'platform.active')}</td><td><Button size="sm" onClick={() => inspect(row)}>{t('platform.details')}</Button>{area === 'companies' && <Button size="sm" onClick={() => edit('metadata', row)}>{t('platform.notes')}</Button>}<Button size="sm" onClick={() => edit(area === 'companies' ? 'companyStatus' : 'userStatus', row)}>{t('platform.changeStatus')}</Button></td></tr>)}</tbody></table>{!data.isPending && !data.error && search.trim() === settledSearch && items.length === 0 && <p role="status">{directorySearch ? t('platform.noSearchResults') : t('platform.noDirectoryRecords')}</p>}</>}
      {detail && <section><h2>{detail.business_name || detail.full_name}</h2><p>{detail.platform_notes || detail.email}</p><ul>{(detail.members || detail.memberships || []).map((m) => <li key={m.user_id || m.tenant_id}>{m.user_id || m.tenant_id}: {m.role}{m.removed_at ? ` · ${t('platform.removed')}` : ''} {(!m.removed_at || m.platform_suspended_at) && <Button size="sm" onClick={() => edit('membershipStatus', m)}>{t('platform.changeStatus')}</Button>}</li>)}</ul></section>}
      {area === 'team' && data.data && <><Button onClick={() => edit('invite')}>{t('platform.invite')}</Button><table><thead><tr><th>{t('platform.name')}</th><th>{t('platform.status')}</th><th>{t('platform.actions')}</th></tr></thead><tbody>{data.data.members.map((m) => <tr key={m.user_id}><td>{m.full_name}<br />{m.email}</td><td>{t(`platform.${m.role}`)} · {t(`platform.${m.status}`)}</td><td>{owner && m.role !== 'owner' && <><Button onClick={() => edit('suspendMember', m)}>{t('platform.changeStatus')}</Button><Button onClick={() => edit('removeMember', m)}>{t('platform.remove')}</Button>{m.status === 'active' && <Button onClick={() => edit('transfer', m)}>{t('platform.transfer')}</Button>}</>}</td></tr>)}</tbody></table><h2>{t('platform.invitations')}</h2>{data.data.invitations.map((i) => <p key={i.invitation_id}>{i.email} · {new Date(i.expires_at).toLocaleString()} · {t(`platform.${i.status}`)} <Button onClick={() => edit('resend', i)}>{t('platform.resend')}</Button> <Button onClick={() => edit('cancel', i)}>{t('platform.cancel')}</Button></p>)}</>}
      {area === 'audit' && <table><thead><tr><th>{t('platform.actions')}</th><th>{t('platform.name')}</th><th>{t('platform.reason')}</th><th>{t('platform.status')}</th></tr></thead><tbody>{items.map((entry) => <tr key={entry.audit_id}><td>{entry.action}<br />{new Date(entry.created_at).toLocaleString()}</td><td>{entry.actor_user_id}<br />{entry.actor_role}</td><td>{entry.reason}</td><td>{entry.outcome}</td></tr>)}</tbody></table>}
      {area === 'settings' && data.data && <section><p>{t('platform.supportEmail')}: {data.data.support_email || '—'}</p><Button onClick={() => edit('settings')}>{t('platform.edit')}</Button><p><Link to="/forgot-password">{t('platform.resetPassword')}</Link></p></section>}
      {['companies', 'users', 'audit', 'team'].includes(area) && <div className="platform-actions"><Button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>{t('platform.previous')}</Button><Button disabled={area === 'team' ? (data.data?.members?.length || 0) < 50 && (data.data?.invitations?.length || 0) < 50 : typeof data.data?.total === 'number' ? offset + items.length >= data.data.total : items.length < 50} onClick={() => setOffset(offset + 50)}>{t('platform.next')}</Button></div>}
      {editor && <form onSubmit={submit} className="platform-editor"><h2>{t(`platform.${editor.type}`)}</h2>{editor.type === 'transfer' && <p role="alert">{t('platform.transferWarning')}</p>}{['invite', 'metadata', 'settings'].includes(editor.type) && <Input label={t(editor.type === 'metadata' ? 'platform.notes' : 'platform.email')} type={editor.type === 'metadata' ? 'text' : 'email'} required={editor.type !== 'metadata'} maxLength={editor.type === 'metadata' ? 10000 : 255} value={value} onChange={(e) => setValue(e.target.value)} />}<Input label={t('platform.reason')} required maxLength={2000} value={reason} onChange={(e) => setReason(e.target.value)} /><div className="platform-actions"><Button type="submit" loading={busy}>{t('platform.confirm')}</Button><Button onClick={() => setEditor(null)} disabled={busy}>{t('platform.cancel')}</Button></div></form>}
      {area === 'approvals' && owner && <form className="platform-editor" onSubmit={async (event) => { event.preventDefault(); requestId.current ||= crypto.randomUUID(); const ok = await act(() => api.approve({ request_id: requestId.current, kind: approval.kind, subject: approval.subject, terms: { description: approval.description }, expires_at: new Date(approval.expires_at).toISOString(), reason })); if (ok) { requestId.current = null; setApproval({ ...approval, subject: '', description: '' }); } }}><h2>{t('platform.approvals')}</h2><p>{t('platform.approvalNotice')}</p><label>{t('platform.kind')}<select value={approval.kind} onChange={(e) => { requestId.current = null; setApproval({ ...approval, kind: e.target.value }); }}>{['below_floor_price', 'manual_access', 'provider_spending'].map((k) => <option key={k} value={k}>{t(`platform.${k}`)}</option>)}</select></label><Input label={t('platform.reference')} required maxLength={255} value={approval.subject} onChange={(e) => { requestId.current = null; setApproval({ ...approval, subject: e.target.value }); }} /><Input label={t('platform.terms')} required value={approval.description} onChange={(e) => { requestId.current = null; setApproval({ ...approval, description: e.target.value }); }} /><Input label={t('platform.expires')} type="datetime-local" required value={approval.expires_at} onChange={(e) => { requestId.current = null; setApproval({ ...approval, expires_at: e.target.value }); }} /><Input label={t('platform.reason')} required maxLength={2000} value={reason} onChange={(e) => setReason(e.target.value)} /><Button type="submit" loading={busy}>{t('platform.confirm')}</Button></form>}
    </>}
  </main>;
}
