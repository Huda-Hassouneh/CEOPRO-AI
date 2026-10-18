import { useState } from 'react';
import { Database, Plug } from 'lucide-react';
import { ApexButton } from '../../../shared/components/apex/Apex.jsx';
import { dataConnectionsApi, SALES_FIELDS } from '../api/dataConnectionsApi.js';

const FREQUENCIES = [15, 60, 360, 1440];
const emptyMapping = () => Object.fromEntries(SALES_FIELDS.map((f) => [f.key, '']));

// Connects the company's own POS/ERP API or database: where it is, how to
// sign in, and which of its fields hold each part of a sale.
export function ConnectSystemForm({ kind, t, onDone, onCancel }) {
  const [form, setForm] = useState({
    name: '', baseUrl: '', recordsPath: '', pageParam: 'page', authHeader: 'Authorization', authScheme: 'Bearer', token: '',
    host: '', port: '5432', dbname: '', user: '', password: '', query: 'SELECT * FROM sales WHERE updated_at > NOW() - INTERVAL \'7 days\'',
    frequency: 60, mapping: emptyMapping(),
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (key) => (event) => setForm({ ...form, [key]: event.target.value });
  const setMap = (key) => (event) => setForm({ ...form, mapping: { ...form.mapping, [key]: event.target.value } });
  const mappingDone = SALES_FIELDS.filter((f) => f.required).every((f) => form.mapping[f.key].trim());
  const valid = form.name.trim() && mappingDone && (kind === 'api'
    ? /^https:\/\/\S+\.\S+/.test(form.baseUrl.trim())
    : form.host.trim() && Number(form.port) > 0 && form.dbname.trim() && form.user.trim() && form.password && /^\s*select\b/i.test(form.query));

  const submit = async (event) => {
    event.preventDefault();
    if (!valid || busy) return;
    setBusy(true);
    setError(null);
    try {
      await (kind === 'api' ? dataConnectionsApi.connectApi(form) : dataConnectionsApi.connectDatabase(form));
      onDone();
    } catch (err) {
      const status = err?.response?.status;
      setError(status === 422 && typeof err.response.data?.detail === 'string' ? err.response.data.detail
        : status === 403 ? t('connectData.system.adminOnly') : t('connectData.system.failed'));
      setBusy(false);
    }
  };

  const field = (key, label, props = {}) => (
    <label className="setup-field"><span>{label}</span><input className="apex-input" value={form[key]} onChange={set(key)} {...props} /></label>
  );

  return (
    <form className="setup-form connect-system-form" onSubmit={submit} noValidate>
      <p className="apex-muted">{t(`connectData.system.${kind}Intro`)}</p>
      {field('name', t('connectData.system.name'), { placeholder: t('connectData.system.namePlaceholder'), maxLength: 120 })}
      {kind === 'api' ? (
        <>
          {field('baseUrl', t('connectData.system.baseUrl'), { placeholder: 'https://pos.example.com/api/sales', dir: 'ltr', inputMode: 'url' })}
          <div className="setup-row">
            {field('recordsPath', t('connectData.system.recordsPath'), { placeholder: 'data.items', dir: 'ltr' })}
            {field('pageParam', t('connectData.system.pageParam'), { dir: 'ltr' })}
          </div>
          <div className="setup-row">
            {field('authHeader', t('connectData.system.authHeader'), { dir: 'ltr' })}
            {field('authScheme', t('connectData.system.authScheme'), { dir: 'ltr' })}
          </div>
          {field('token', t('connectData.system.token'), { type: 'password', autoComplete: 'off', dir: 'ltr' })}
        </>
      ) : (
        <>
          <div className="setup-row">
            {field('host', t('connectData.system.host'), { placeholder: 'db.yourcompany.com', dir: 'ltr' })}
            {field('port', t('connectData.system.port'), { inputMode: 'numeric', dir: 'ltr' })}
          </div>
          {field('dbname', t('connectData.system.dbname'), { dir: 'ltr' })}
          <div className="setup-row">
            {field('user', t('connectData.system.user'), { autoComplete: 'off', dir: 'ltr' })}
            {field('password', t('connectData.system.password'), { type: 'password', autoComplete: 'new-password', dir: 'ltr' })}
          </div>
          <label className="setup-field"><span>{t('connectData.system.query')}</span>
            <textarea className="apex-input" rows={3} dir="ltr" value={form.query} onChange={set('query')} /></label>
          <p className="apex-muted setup-note">{t('connectData.system.readOnly')}</p>
        </>
      )}
      <fieldset className="setup-field">
        <legend>{t('connectData.system.mapping')}</legend>
        <p className="apex-muted setup-note">{t('connectData.system.mappingHint')}</p>
        <div className="connect-mapping">
          {SALES_FIELDS.map((f) => (
            <label key={f.key}>
              <span>{t(`connectData.system.fields.${f.key}`)}{f.required ? ' *' : ''}</span>
              <input className="apex-input" dir="ltr" value={form.mapping[f.key]} onChange={setMap(f.key)} placeholder={f.key} />
            </label>
          ))}
        </div>
      </fieldset>
      <label className="setup-field"><span>{t('connectData.system.frequency')}</span>
        <select className="apex-select" value={form.frequency} onChange={set('frequency')}>
          {FREQUENCIES.map((m) => <option key={m} value={m}>{t(`connectData.system.every.${m}`)}</option>)}
        </select></label>
      {error && <p className="market-scan__note is-error" role="alert">{error}</p>}
      <div className="setup-actions">
        <ApexButton variant="ghost" onClick={onCancel} disabled={busy}>{t('common.cancel')}</ApexButton>
        <ApexButton type="submit" icon={kind === 'api' ? Plug : Database} loading={busy} disabled={!valid}>{t('connectData.system.connect')}</ApexButton>
      </div>
    </form>
  );
}

export default ConnectSystemForm;
