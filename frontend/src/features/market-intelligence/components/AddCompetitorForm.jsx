import { useState } from 'react';
import Button from '../../../shared/components/ui/Button.jsx';
import Input from '../../../shared/components/ui/Input.jsx';
export function AddCompetitorForm({ t, onSubmit, onCancel, busy = false, error }) {
  const [values,setValues] = useState({ name:'',website:'',industry:'' });
  const [errors,setErrors] = useState({});
  const update = key => event => setValues(current => ({ ...current,[key]:event.target.value }));
  const submit = event => {
    event.preventDefault(); if (busy) return;
    const next = {}; if (!values.name.trim()) next.name=t('market.modal.required');
    try { const url=new URL(values.website); if (!['http:','https:'].includes(url.protocol) || url.username || url.password || !url.hostname.includes('.')) throw new Error(); }
    catch { next.website=t('market.modal.invalidUrl'); }
    setErrors(next); if (!Object.keys(next).length) onSubmit(Object.fromEntries(Object.entries(values).map(([key,value])=>[key,value.trim()])));
  };
  return <form className="add-competitor-form" onSubmit={submit}>
    <p>{t('competitorManagement.addNotice')}</p>
    <Input label={t('market.modal.name')} value={values.name} onChange={update('name')} maxLength={255} error={errors.name} required disabled={busy} />
    <Input label={t('market.modal.website')} value={values.website} onChange={update('website')} maxLength={2048} error={errors.website} required disabled={busy} />
    <Input label={t('market.controls.industry')} value={values.industry} onChange={update('industry')} maxLength={150} disabled={busy} />
    {error && <p role="alert">{error}</p>}
    <Button type="submit" fullWidth disabled={busy}>{t(busy ? 'competitorManagement.saving' : 'market.modal.submit')}</Button>
    <button type="button" className="add-competitor-cancel" disabled={busy} onClick={onCancel}>{t('market.modal.cancel')}</button>
  </form>;
}
