import { useState } from 'react';
import { UserPlus } from 'lucide-react';
import { useAdmin, useAdminText, useAdminQuery, useAdminMutation, roleDescriptions } from '../components/AdminContext.jsx';
import { Heading, Identity, Badge, DateValue, Button, Confirmation, Field, SelectField } from '../components/AdminUI.jsx';
import { AdminTable, useTableParams } from '../components/AdminTable.jsx';
import { PLATFORM_ROLES } from '../permissions/platformPermissions.js';
import { validEmail } from '../api/validation.js';

export function AdminTeamPage() {
  const { t } = useAdminText(), admin = useAdmin(), table = useTableParams(), query = useAdminQuery('admin-team', table.params);
  const [dialog, setDialog] = useState(null), [email, setEmail] = useState(''), [role, setRole] = useState('VIEWER'), [action, setAction] = useState('role');
  const invite = dialog?.type === 'invite';
  const permission = invite || action === 'resend' ? 'adminTeam.invite' : ['remove', 'cancel'].includes(action) ? 'adminTeam.remove' : 'adminTeam.roles.manage';
  const mutation = useAdminMutation(permission);
  const start = member => { setDialog({ type: 'member', member }); setRole(member.role); setAction(member.status === 'pending' ? 'resend' : 'role'); };
  const execute = async () => { const member = dialog.member; try { await mutation.mutateAsync({ domain: 'admin-team', id: member?.id, action: invite ? 'invite' : action, payload: invite ? { email, role } : action === 'role' ? { role } : action === 'status' ? { status: member.status === 'active' ? 'inactive' : 'active' } : {} }); setDialog(null); } catch { /* Keep form values for correction. */ } };
  return <><Heading title="adminTeam" description="adminTeamDescription" actions={admin.can('adminTeam.invite') && <Button leadingIcon={<UserPlus size={17} />} onClick={() => { setEmail(''); setRole('admin'); setDialog({ type: 'invite' }); }}>{t('invite')}</Button>} /><AdminTable title={t('adminTeam')} query={query} table={table} filters={[{ key: 'role', options: PLATFORM_ROLES }, { key: 'status', options: ['active', 'inactive', 'pending'] }]} columns={[{ key: 'name', render: m => <Identity name={m.name} email={m.email} /> }, { key: 'role', render: m => <Badge value={m.role} /> }, { key: 'status', render: m => <Badge value={m.status} /> }, { key: 'createdAt', label: 'joined', render: m => <DateValue value={m.createdAt} /> }]} rowAction={admin.can('adminTeam.roles.manage') ? member => <Button variant="ghost" size="sm" onClick={() => start(member)}>{t('memberActions')}</Button> : undefined} />
  <Confirmation confirmLabel={invite ? 'sendInvitation' : 'confirm'} open={Boolean(dialog)} title={t(invite ? 'invite' : 'memberActions')} busy={mutation.isPending} disabled={invite ? !validEmail(email) : action === 'role' && role === dialog?.member?.role} onClose={() => setDialog(null)} onConfirm={execute}>{invite ? <><p>{t('inviteNote')}</p><Field label={t('email')} type="email" value={email} autoComplete="email" required onChange={e => setEmail(e.target.value)} /></> : dialog && <><Identity name={dialog.member.name} email={dialog.member.email} /><p>{t('accessNote')}</p><SelectField label={t('action')} value={action} onChange={setAction} options={dialog.member.status === 'pending' ? [{ value: 'resend', label: t('resend') }, { value: 'cancel', label: t('cancelInvitation') }] : [{ value: 'role', label: t('changeRole') }, { value: 'status', label: t(dialog.member.status === 'active' ? 'deactivate' : 'reactivate') }, { value: 'remove', label: t('remove') }]} /></>}{(invite || action === 'role') && <><SelectField label={t(invite ? 'role' : 'newRole')} value={role} onChange={setRole} options={PLATFORM_ROLES.map(value => ({ value, label: t(value) }))} />{!invite && dialog && <p>{t('currentRole')}: <b>{t(dialog.member.role)}</b> → {t(role)}</p>}<div className="pa-notice">{t(roleDescriptions[role])}</div></>}{!invite && action !== 'role' && <p className="pa-error">{t('sensitive')}</p>}</Confirmation></>;
}

