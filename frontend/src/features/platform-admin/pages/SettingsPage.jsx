import { useState } from 'react';
import { useAdminQuery, useAdminMutation, useAdminText } from '../components/AdminContext.jsx';
import { Heading, Panel, QueryState, Field, SelectField, Button, Confirmation, UnsavedGuard } from '../components/AdminUI.jsx';
import { ChangesTable, collectChanges } from './PlansPage.jsx';
import { validEmail } from '../api/validation.js';

function SettingsEditor({ settings }) {
  const { t } = useAdminText(), [draft, setDraft] = useState(settings), [baseline, setBaseline] = useState(settings), [review, setReview] = useState(false);
  const mutation = useAdminMutation('platformSettings.manage'), dirty = JSON.stringify(draft) !== JSON.stringify(baseline);
  const set = (key, value) => setDraft(v => ({ ...v, [key]: value }));
  const save = async () => { try { const result = await mutation.mutateAsync({ domain: 'settings', action: 'update', payload: draft }); setDraft(result); setBaseline(result); setReview(false); } catch { /* Retain unsaved edits. */ } };
  return <><UnsavedGuard dirty={dirty} /><form onSubmit={e => { e.preventDefault(); setReview(true); }}><Panel title={t('general')}><div className="pa-editor-body pa-form-grid"><Field label={t('platformName')} required maxLength={100} value={draft.name} onChange={e => set('name', e.target.value)} /><Field label={t('supportEmail')} required type="email" value={draft.supportEmail} onChange={e => set('supportEmail', e.target.value)} /></div></Panel><Panel title={t('localization')}><div className="pa-editor-body pa-form-grid"><SelectField label={t('defaultLanguage')} value={draft.language} onChange={v => set('language', v)} options={[{ value: 'en', label: t('english') }, { value: 'ar', label: t('arabic') }]} /><Field label={t('currency')} value={draft.currency} readOnly /><p className="pa-muted">{t('currencyNote')}</p></div></Panel><div className="pa-editor-footer"><Button variant="outline" disabled={!dirty} onClick={() => setDraft(baseline)}>{t('cancel')}</Button><Button type="submit" disabled={!dirty || !draft.name.trim() || !validEmail(draft.supportEmail)}>{t('review')}</Button></div></form><Confirmation open={review} busy={mutation.isPending} onClose={() => setReview(false)} onConfirm={save}><p>{t('sensitive')}</p><ChangesTable changes={collectChanges(baseline, draft)} /></Confirmation></>;
}
export function PlatformSettingsPage() { const query = useAdminQuery('settings'); return <><Heading title="settings" description="settingsDescription" /><QueryState query={query}>{query.data && <SettingsEditor settings={query.data} />}</QueryState></>; }
