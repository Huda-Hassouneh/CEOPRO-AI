import { useState } from 'react';
import { X } from 'lucide-react';
import Badge from '../../../shared/components/ui/Badge.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import Input from '../../../shared/components/ui/Input.jsx';
import Select from '../../../shared/components/ui/Select.jsx';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import { SettingsSection } from './SettingsSection.jsx';
import { useTargetMarkets } from '../hooks/useTargetMarkets.js';
import { useUpdateTargetMarkets } from '../hooks/useUpdateTargetMarkets.js';

// Explicit commercial Target Markets - deliberately its own settings
// section, separate from the company profile above and from Market
// Intelligence's own Search Scope page: this answers "which countries do
// we want to COMPETE IN", never "where is the business registered" or
// "how far around us should discovery search". Generic for any industry
// and any country.
//
// Three market_type shapes, matching backend/src/market_scraper/
// company_target_markets.py's own contract exactly:
// - COUNTRY: a free-text 2-letter ISO code, same convention as
//   SearchScopeForm.jsx's own operatingCountries field.
// - REGION: free text (e.g. "Middle East", "Southeast Asia") - never a
//   fixed dropdown of named regions, since this platform has no
//   authoritative region-to-country mapping for any industry or country.
// - GLOBAL: "compete everywhere" - mutually exclusive with every other
//   declared entry (the backend rejects mixing it with COUNTRY/REGION
//   entries), so selecting it clears any other declared markets.
function marketLabel(entry, t) {
  if (entry.market_type === 'GLOBAL') return t('settings.targetMarkets.type.global');
  if (entry.market_type === 'REGION') return entry.region_name;
  return entry.country_code;
}

function marketKey(entry) {
  return `${entry.market_type}:${entry.country_code || entry.region_name || ''}`;
}

export function TargetMarketsSettings({ permissions, t }) {
  const query = useTargetMarkets();
  const mutation = useUpdateTargetMarkets();
  const [marketType, setMarketType] = useState('COUNTRY');
  const [draft, setDraft] = useState('');
  const [error, setError] = useState('');

  if (query.isPending) return <Skeleton height="180px" variant="rectangular" />;
  if (query.isError) {
    return <SettingsSection title={t('settings.targetMarkets.title')}>
      <p className="settings-inline-error">{t('settings.targetMarkets.loadError')}</p>
    </SettingsSection>;
  }

  const markets = query.data || [];

  const save = (nextMarkets) => {
    setError('');
    mutation.mutate(nextMarkets, {
      onError: (err) => setError(err?.response?.data?.detail || t('settings.targetMarkets.saveError')),
    });
  };

  const addMarket = (event) => {
    event.preventDefault();

    if (marketType === 'GLOBAL') {
      // Mutually exclusive with everything else - a real replace, not an
      // append, matching the backend's own rejection of GLOBAL combined
      // with other entries.
      save([{ market_type: 'GLOBAL', country_code: null, region_name: null }]);
      return;
    }

    const alreadyGlobal = markets.some((entry) => entry.market_type === 'GLOBAL');
    if (alreadyGlobal) {
      setError(t('settings.targetMarkets.clearGlobalFirst'));
      return;
    }

    if (marketType === 'COUNTRY') {
      const code = draft.trim().toUpperCase();
      if (!/^[A-Z]{2}$/.test(code)) {
        setError(t('settings.targetMarkets.invalidCode'));
        return;
      }
      if (markets.some((entry) => entry.market_type === 'COUNTRY' && entry.country_code === code)) {
        setDraft('');
        return;
      }
      setDraft('');
      save([...markets, { market_type: 'COUNTRY', country_code: code, region_name: null }]);
      return;
    }

    // REGION: free text, never validated against a fixed list.
    const name = draft.trim();
    if (!name) {
      setError(t('settings.targetMarkets.invalidRegion'));
      return;
    }
    if (markets.some((entry) => entry.market_type === 'REGION' && entry.region_name?.toLowerCase() === name.toLowerCase())) {
      setDraft('');
      return;
    }
    setDraft('');
    save([...markets, { market_type: 'REGION', country_code: null, region_name: name }]);
  };

  const removeMarket = (entry) => save(markets.filter((existing) => marketKey(existing) !== marketKey(entry)));

  const typeOptions = [
    { value: 'COUNTRY', label: t('settings.targetMarkets.type.country') },
    { value: 'REGION', label: t('settings.targetMarkets.type.region') },
    { value: 'GLOBAL', label: t('settings.targetMarkets.type.global') },
  ];

  return <SettingsSection title={t('settings.targetMarkets.title')} subtitle={t('settings.targetMarkets.subtitle')}>
    {markets.length === 0
      ? <p className="settings-capability-note">{t('settings.targetMarkets.empty')}</p>
      : <div className="settings-target-markets-list">
          {markets.map((entry) => <Badge key={marketKey(entry)} variant={entry.market_type === 'GLOBAL' ? 'primary' : 'neutral'}>
            {marketLabel(entry, t)}
            {permissions.canEditCompany && <button
              type="button"
              className="settings-target-markets-remove"
              aria-label={t('settings.targetMarkets.remove', { code: marketLabel(entry, t) })}
              disabled={mutation.isPending}
              onClick={() => removeMarket(entry)}
            ><X size={12} /></button>}
          </Badge>)}
        </div>}

    {permissions.canEditCompany
      ? <form className="settings-target-markets-form" onSubmit={addMarket}>
          <Select
            className="settings-target-markets-type"
            value={marketType}
            onChange={(event) => { setMarketType(event.target.value); setDraft(''); setError(''); }}
            options={typeOptions}
            aria-label={t('settings.targetMarkets.typeLabel')}
            disabled={mutation.isPending}
          />
          {marketType !== 'GLOBAL' && <Input
            value={draft}
            onChange={(event) => { setDraft(event.target.value); setError(''); }}
            placeholder={marketType === 'COUNTRY' ? t('settings.targetMarkets.placeholder') : t('settings.targetMarkets.regionPlaceholder')}
            maxLength={marketType === 'COUNTRY' ? 2 : 100}
            aria-label={marketType === 'COUNTRY' ? t('settings.targetMarkets.inputLabel') : t('settings.targetMarkets.regionInputLabel')}
            error={error}
            disabled={mutation.isPending}
          />}
          <Button type="submit" size="sm" disabled={mutation.isPending || (marketType !== 'GLOBAL' && !draft.trim())}>
            {mutation.isPending ? t('settings.targetMarkets.saving') : t('settings.targetMarkets.add')}
          </Button>
          {marketType === 'GLOBAL' && error === '' && markets.length > 0 && !markets.some((entry) => entry.market_type === 'GLOBAL')
            ? <p className="settings-capability-note">{t('settings.targetMarkets.globalReplacesAll')}</p>
            : null}
          {error && marketType === 'GLOBAL' ? <p className="settings-inline-error">{error}</p> : null}
        </form>
      : <p className="settings-capability-note">{t('settings.company.readOnly')}</p>}
  </SettingsSection>;
}
