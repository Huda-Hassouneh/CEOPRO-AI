import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useI18n } from '../../app/providers/I18nProvider.jsx';
import { useAuthStore } from '../auth/store/authStore.js';
import Card from '../../shared/components/ui/Card.jsx';
import Table from '../../shared/components/ui/Table.jsx';
import Button from '../../shared/components/ui/Button.jsx';
import Input from '../../shared/components/ui/Input.jsx';
import Select from '../../shared/components/ui/Select.jsx';
import Modal from '../../shared/components/ui/Modal.jsx';
import Skeleton from '../../shared/components/ui/Skeleton.jsx';
import Toast from '../../shared/components/ui/Toast.jsx';
import EmptyState from '../../shared/components/ui/EmptyState.jsx';
import { platformBillingApi } from './platformBillingApi.js';
import { ACCOUNTING_UNITS, accountingRows, decimalText, emptyPrice, pricePayload, priceStatus } from './providerAccounting.js';
import './providerAccounting.css';

export function ProviderAccounting({ canManage = false, api = platformBillingApi }) {
  const { t } = useI18n();
  const actor = useAuthStore(state => state.user?.id || state.user?.user_id);
  const queryClient = useQueryClient();
  const key = ['platform', actor, 'provider-accounting'];
  const query = useQuery({ queryKey: key, queryFn: api.providerAccounting, retry: false });
  const [form, setForm] = useState(null);
  const [locked, setLocked] = useState(false);
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState(null);
  const [confirming, setConfirming] = useState(false);
  const text = name => t(`billing.providerAccounting.${name}`);
  const open = row => {
    setForm(row ? Object.fromEntries(Object.keys(emptyPrice()).map(k => [k, ['unit_cost_usd', 'safety_margin'].includes(k) ? decimalText(row[k]) : row[k] ?? ''])) : emptyPrice());
    setLocked(Boolean(row)); setErrors({}); setFeedback(null); setConfirming(false);
  };
  const close = () => { if (!saving) { setForm(null); setConfirming(false); } };
  const submit = async event => {
    event.preventDefault();
    const payload = pricePayload(form);
    setErrors(payload.errors || {});
    if (payload.errors) return;
    if (!confirming) { setConfirming(true); return; }
    setSaving(true); setFeedback(null);
    try {
      const saved = await api.saveProviderAccounting(payload.body);
      queryClient.setQueryData(key, saved);
      setForm(null); setConfirming(false); setFeedback({ message: text('saved'), variant: 'success' });
    } catch {
      // Do not echo raw server bodies, URLs, SQL or validation input values.
      setFeedback({ message: text('saveError'), variant: 'error' });
      setConfirming(false);
    } finally { setSaving(false); }
  };
  const bool = value => value ? t('common.yes') : t('common.no');
  const fields = ['budget_kind', 'provider', 'operation', 'unit', 'unit_cost_usd', 'safety_margin', 'charged_on_failure', 'cost_is_final', 'source', 'verified_at', 'configured_by', 'reason', 'updated_at'];
  const columns = fields.map(field => ({ key: field, header: text(field), render: row => {
    const value = ['charged_on_failure', 'cost_is_final'].includes(field) ? bool(row[field])
      : row[field] == null ? '—' : ['unit_cost_usd', 'safety_margin'].includes(field) ? decimalText(row[field]) : row[field];
    return <span className={['source', 'reason'].includes(field) ? 'provider-accounting-provenance' : 'provider-accounting-value'}>{value}</span>;
  } }));
  columns.splice(5, 0, { key: 'status', header: text('status'), render: row => text(priceStatus(row)) });
  if (canManage) columns.push({ key: 'actions', header: t('billing.catalog.actions'), render: row => <Button size="sm" variant="secondary" onClick={() => open(row)}>{t('common.edit')}</Button> });
  return <section className="provider-accounting" aria-label={text('title')}>
    <Card>
      <h2>{text('title')}</h2><p>{text('description')}</p>
      {canManage && <Button onClick={() => open(null)}>{text('add')}</Button>}
      {query.isPending ? <div role="status" aria-label={t('common.loading')}><Skeleton height="120px" /></div>
        : query.isError ? <div role="alert"><p>{text('loadError')}</p><Button onClick={() => query.refetch()}>{text('retry')}</Button></div>
          : query.data ? <Table ariaLabel={text('title')} columns={columns} data={accountingRows(query.data.schedules)} />
            : <EmptyState title={text('empty')} />}
    </Card>
    {feedback && !form && <Toast {...feedback} onClose={() => setFeedback(null)} />}
    <Modal isOpen={Boolean(form)} onClose={close} title={text('edit')} closeLabel={t('common.close')} maxWidth="640px">
      {form && <form onSubmit={submit} className="provider-accounting-form">
        {feedback?.variant === 'error' && <p role="alert">{feedback.message}</p>}
        {confirming ? <><p role="alert">{text('confirm')}</p><p dir="ltr">{form.budget_kind} / {form.provider} / {form.operation} / {form.unit}: USD {form.unit_cost_usd}</p>
          <p>{text('safety_margin')}: {form.safety_margin || '—'} · {text('charged_on_failure')}: {bool(form.charged_on_failure)} · {text('cost_is_final')}: {bool(form.cost_is_final)}</p>
          <p>{text('source')}: {form.source}</p><p>{text('reason')}: {form.reason}</p></>
          : <>
            {['budget_kind', 'unit'].map(field => <Select key={field} label={text(field)} value={form[field]} disabled={locked || saving}
              onChange={e => setForm({ ...form, [field]: e.target.value })} options={(field === 'unit' ? ACCOUNTING_UNITS : ['data', 'ai']).map(value => ({ value, label: value }))} />)}
            {['provider', 'operation', 'unit_cost_usd', 'safety_margin', 'source', 'verified_at', 'reason'].map(field => <Input key={field} label={text(field)}
              value={form[field]} type={field === 'verified_at' ? 'date' : 'text'} inputMode={['unit_cost_usd', 'safety_margin'].includes(field) ? 'decimal' : undefined}
              maxLength={field === 'provider' ? 60 : field === 'operation' ? 120 : 2000} disabled={saving || (locked && ['provider', 'operation'].includes(field))}
              error={errors[field] ? text('invalid') : undefined} hint={field === 'safety_margin' ? text('marginHint') : undefined}
              onChange={e => setForm({ ...form, [field]: e.target.value })} />)}
            {['charged_on_failure', 'cost_is_final'].map(field => <label key={field}><input type="checkbox" checked={form[field]} disabled={saving}
              onChange={e => setForm({ ...form, [field]: e.target.checked })} /> {text(field)}</label>)}
          </>}
        <div className="billing-form-actions">
          <Button type="button" variant="secondary" disabled={saving} onClick={confirming ? () => setConfirming(false) : close}>{t('common.cancel')}</Button>
          <Button type="submit" disabled={saving}>{saving ? t('common.loading') : confirming ? t('common.confirm') : t('common.save')}</Button>
        </div>
      </form>}
    </Modal>
  </section>;
}
