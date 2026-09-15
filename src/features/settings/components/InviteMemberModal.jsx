import { useState } from 'react';
import Button from '../../../shared/components/ui/Button.jsx';
import Input from '../../../shared/components/ui/Input.jsx';
import Modal from '../../../shared/components/ui/Modal.jsx';
import Select from '../../../shared/components/ui/Select.jsx';
import { validateEmail, firstValidationError } from '../../auth/validation/authValidation.js';
import { useInviteMember } from '../hooks/useInviteMember.js';

export default function InviteMemberModal({ open, capabilities, permissions, onClose, members, invitations, companyId, t, onNotice }) {
  const [values, setValues] = useState({ email: '', role: 'viewer' });
  const [error, setError] = useState('');
  const mutation = useInviteMember();
  const roles = ['admin', 'editor', 'viewer'].map((role) => ({ value: role, label: t(`settings.roles.${role}.label`) }));
  const close = () => { setError(''); setValues({ email: '', role: 'viewer' }); onClose(); };
  const submit = async (event) => {
    event.preventDefault();
    if (!permissions.canInviteMembers || !capabilities.invite || mutation.isPending || !roles.some((role) => role.value === values.role)) return;
    const normalizedEmail = values.email.trim().toLowerCase();
    const validationError = firstValidationError(validateEmail(normalizedEmail));
    if (validationError) return setError(t(validationError.key, validationError.params));
    if (members.some((member) => member.email?.toLowerCase() === normalizedEmail)) return setError(t('settings.team.invite.existing'));
    if (invitations.some((invite) => invite.email?.toLowerCase() === normalizedEmail)) return setError(t('settings.team.invite.pending'));
    try {
      const result = await mutation.mutateAsync({ companyId, email: normalizedEmail, role: values.role });
      if (!result.sent) return onNotice('info', t('settings.team.invite.unavailable'));
      onNotice('success', t('settings.team.invite.sent'));
      close();
    } catch { onNotice('error', t('settings.team.invite.failed')); }
  };
  return <Modal isOpen={open} onClose={close} title={t('settings.team.invite.title')} closeLabel={t('common.close')} maxWidth="560px" footer={<><Button variant="outline" onClick={close}>{t('settings.common.cancel')}</Button><Button disabled={!permissions.canInviteMembers || !capabilities.invite} onClick={submit} loading={mutation.isPending} loadingLabel={t('settings.team.invite.sending')}>{t('settings.team.invite.send')}</Button></>}>
    {!capabilities.invite && <p className="settings-capability-note">{t('settings.team.invite.unavailable')}</p>}<form className="settings-invite-form" onSubmit={submit}><Input type="email" label={t('settings.team.invite.email')} value={values.email} onChange={(event) => { setValues({ ...values, email: event.target.value }); setError(''); }} error={error} /><Select label={t('settings.team.invite.role')} value={values.role} onChange={(event) => setValues({ ...values, role: event.target.value })} options={roles} /><div className="settings-role-descriptions">{roles.map((role) => <p key={role.value}><strong>{role.label}</strong><span>{t(`settings.roles.${role.value}.description`)}</span></p>)}</div></form>
  </Modal>;
}
