import { useState } from 'react';
import { ShoppingBag, Store } from 'lucide-react';
import { ApexButton } from '../../../shared/components/apex/Apex.jsx';
import { dataConnectionsApi } from '../api/dataConnectionsApi.js';

const FREQUENCIES = [15, 60, 360, 1440];

export function ConnectStoreForm({ provider, t, onDone, onCancel }) {
  const [url, setUrl] = useState('');
  const [consumerKey, setConsumerKey] = useState('');
  const [consumerSecret, setConsumerSecret] = useState('');
  const [frequency, setFrequency] = useState(60);
  const [consent, setConsent] = useState(false);
  const [includeTestOrders, setIncludeTestOrders] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const shopify = provider === 'shopify';

  const validShop = (() => {
    try {
      const candidate = url.includes('://') ? new URL(url) : new URL(`https://${url}`);
      return candidate.protocol === 'https:' && !candidate.port && !candidate.username && !candidate.password
        && !candidate.search && !candidate.hash && ['', '/'].includes(candidate.pathname)
        && /^[a-z0-9][a-z0-9-]{0,62}\.myshopify\.com$/i.test(candidate.hostname);
    } catch { return false; }
  })();
  const validWoo = (() => {
    try {
      const candidate = new URL(url);
      return candidate.protocol === 'https:' && !candidate.port && !candidate.username && !candidate.password
        && !candidate.search && !candidate.hash && !/%|\\/.test(candidate.pathname)
        && candidate.hostname.includes('.');
    } catch { return false; }
  })();
  const validKeys = /^ck_[a-fA-F0-9]{40}$/.test(consumerKey) && /^cs_[a-fA-F0-9]{40}$/.test(consumerSecret);
  const valid = consent && (shopify ? validShop : validWoo && validKeys);

  const submit = async (event) => {
    event.preventDefault();
    if (!valid || busy) return;
    setBusy(true);
    setError(null);
    try {
      if (shopify) {
        const result = await dataConnectionsApi.beginShopifyConnect({ url, frequency, includeTestOrders });
        window.location.assign(result.authorization_url);
        return;
      }
      await dataConnectionsApi.connectWooCommerce({ url, consumerKey, consumerSecret, frequency });
      onDone();
    } catch (err) {
      const status = err?.response?.status;
      setError(status === 402 ? t('connectData.store.capacityReached')
        : status === 403 ? t('connectData.store.adminOnly')
        : status === 409 ? t('connectData.store.conflict')
          : status === 422 ? t('connectData.store.invalid') : t('connectData.store.failed'));
      setBusy(false);
    }
  };

  const Field = ({ label, value, onChange, ...props }) => (
    <label className="setup-field"><span>{label}</span><input className="apex-input" value={value} onChange={(event) => onChange(event.target.value)} {...props} /></label>
  );

  return (
    <form className="setup-form connect-store-form" onSubmit={submit} noValidate>
      <p className="apex-muted">{t(`connectData.store.${provider}Intro`)}</p>
      <Field label={t('connectData.store.url')} value={url} onChange={setUrl} dir="ltr" inputMode="url"
        autoComplete="url" placeholder={shopify ? 'store-name.myshopify.com' : 'https://shop.example.com'} />
      {!shopify && <>
        <Field label={t('connectData.store.consumerKey')} value={consumerKey} onChange={setConsumerKey}
          type="password" autoComplete="off" dir="ltr" />
        <Field label={t('connectData.store.consumerSecret')} value={consumerSecret} onChange={setConsumerSecret}
          type="password" autoComplete="new-password" dir="ltr" />
      </>}
      <label className="setup-field"><span>{t('connectData.store.frequency')}</span>
        <select className="apex-select" value={frequency} onChange={(event) => setFrequency(Number(event.target.value))}>
          {FREQUENCIES.map((minutes) => <option key={minutes} value={minutes}>{t(`connectData.system.every.${minutes}`)}</option>)}
        </select>
      </label>
      <label className="connect-store-consent">
        <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
        <span>{t('connectData.store.consent')}</span>
      </label>
      {shopify && <label className="connect-store-consent">
        <input type="checkbox" checked={includeTestOrders} onChange={(event) => setIncludeTestOrders(event.target.checked)} />
        <span>{t('connectData.store.includeTestOrders')}</span>
      </label>}
      <p className="apex-muted connect-store-note">{t(`connectData.store.${provider}Boundary`)}</p>
      {error && <p className="market-scan__note is-error" role="alert">{error}</p>}
      <div className="setup-actions">
        <ApexButton variant="ghost" onClick={onCancel} disabled={busy}>{t('common.cancel')}</ApexButton>
        <ApexButton type="submit" icon={shopify ? Store : ShoppingBag} loading={busy} disabled={!valid}>
          {t(shopify ? 'connectData.store.install' : 'connectData.store.connect')}
        </ApexButton>
      </div>
    </form>
  );
}

export default ConnectStoreForm;
