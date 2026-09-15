import { useState } from 'react';
import { Building2, Globe2, Link2, Share2, Store } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';
import Input from '../../../shared/components/ui/Input.jsx';
import { isNonEmpty } from '../../../shared/utils/validators.js';

export function AddCompetitorForm({ t, onSubmit, onCancel }) {
  const [values, setValues] = useState({ name: '', website: '', amazon: '', shopify: '', linkedin: '', x: '' });
  const [errors, setErrors] = useState({});
  const update = (key) => (event) => setValues((current) => ({ ...current, [key]: event.target.value }));
  const submit = (event) => { event.preventDefault(); const next = {}; if (!isNonEmpty(values.name)) next.name = t('market.modal.required'); if (!isNonEmpty(values.website)) next.website = t('market.modal.required'); else { try { const url = new URL(values.website); if (!['http:', 'https:'].includes(url.protocol)) throw new Error(); } catch { next.website = t('market.modal.invalidUrl'); } } setErrors(next); if (!Object.keys(next).length) onSubmit(values); };
  return <form className="add-competitor-form" onSubmit={submit}><p className="add-competitor-form__subtitle">{t('market.modal.subtitle')}</p><Input label={t('market.modal.name')} value={values.name} onChange={update('name')} error={errors.name} leftIcon={<Building2 size={17} />} required /><Input label={t('market.modal.website')} value={values.website} onChange={update('website')} error={errors.website} leftIcon={<Globe2 size={17} />} required /><div className="add-competitor-form__section"><h3><Store size={17} />{t('market.modal.marketplace')} <small>{t('market.modal.optional')}</small></h3><div className="add-competitor-form__grid"><Input placeholder="amazon.com/stores/..." value={values.amazon} onChange={update('amazon')} leftIcon={<Link2 size={16} />} /><Input placeholder="myshopify.com/..." value={values.shopify} onChange={update('shopify')} leftIcon={<Store size={16} />} /></div></div><div className="add-competitor-form__section"><h3><Share2 size={17} />{t('market.modal.social')} <small>{t('market.modal.optional')}</small></h3><div className="add-competitor-form__grid"><Input placeholder="company-name" value={values.linkedin} onChange={update('linkedin')} /><Input placeholder="@ handle" value={values.x} onChange={update('x')} /></div></div><Button type="submit" fullWidth>{t('market.modal.submit')}</Button><button type="button" className="add-competitor-cancel" onClick={onCancel}>{t('market.modal.cancel')}</button></form>;
}
