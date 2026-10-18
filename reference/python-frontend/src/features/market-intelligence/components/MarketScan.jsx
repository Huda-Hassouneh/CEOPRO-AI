import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CheckCircle2, CircleDashed, MapPin, Radar, RefreshCw, XCircle } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { ApexButton, Panel, Pill, StateBlock } from '../../../shared/components/apex/Apex.jsx';
import { RUN_ACTIVE } from '../api/discoveryApi.js';
import { useDiscoveryRun, useDiscoveryStatus, useStartDiscovery } from '../hooks/useDiscovery.js';

const PROVIDER_ORDER = ['map_listing', 'company_database', 'web_search'];

function ProviderChip({ t, provider, result }) {
  let tone = 'neutral';
  let Icon = CircleDashed;
  // Web search is an optional extra (it needs a free key); not having it is not a fault.
  let note = t(`discovery.providerState.${provider.configured ? 'ready' : provider.provider === 'web_search' ? 'optional' : 'notConnected'}`);
  if (result) {
    if (result.status === 'ok') { tone = 'success'; Icon = CheckCircle2; note = t('discovery.providerState.found', { count: result.found }); }
    else if (result.status === 'failed') { tone = 'danger'; Icon = XCircle; note = t('discovery.providerState.unreachable'); }
    else note = t(`discovery.providerState.${['no_location', 'location_not_found'].includes(result.reason) ? 'noLocation' : provider.provider === 'web_search' ? 'optional' : 'notConnected'}`);
  }
  return <Pill tone={tone} icon={Icon}>{t(`discovery.providers.${provider.provider}`)} · {note}</Pill>;
}

// What the last scan produced at each stage - so hundreds of names are never
// mistaken for usable intelligence. Every figure comes from the run record.
function Coverage({ coverage, t, number }) {
  if (!coverage) return null;
  const rel = coverage.by_relationship || {};
  const outcomes = Object.entries(coverage.websites?.outcomes || {}).sort((a, b) => b[1] - a[1]);
  const rows = [
    [t('discovery.coverage.listings'), t('discovery.coverage.listingsValue', { found: number.format(coverage.listings_found || 0), merged: number.format(coverage.duplicates_merged || 0) })],
    [t('discovery.coverage.relevant'), ['DIRECT', 'INDIRECT', 'RELATED', 'UNVERIFIED'].filter((k) => rel[k]?.count)
      .map((k) => `${t(`discovery.relationship.${k}`)} ${number.format(rel[k].count)}`).join(' · ') || number.format(coverage.relevant_saved || 0)],
    [t('discovery.coverage.websites'), t('discovery.coverage.websitesValue', { read: number.format(coverage.websites?.read || 0), tried: number.format(coverage.websites?.tried || 0), pages: number.format(coverage.websites?.pages_read || 0) })
      + (outcomes.length ? ` (${outcomes.map(([k, n]) => `${t(`intel.statusShort.${k}`, { defaultValue: k })} ${number.format(n)}`).join(', ')})` : '')],
    [t('discovery.coverage.extracted'), t('discovery.coverage.extractedValue', { products: number.format(coverage.products_found || 0), prices: number.format(coverage.prices_found || 0), offers: number.format(coverage.promotions_found || 0) })],
    [t('discovery.coverage.matched'), t('discovery.coverage.matchedValue', { products: number.format(coverage.products_with_competitor_prices || 0), prices: number.format(coverage.prices_matched || 0), competitors: number.format(coverage.competitors_with_matched_prices || 0) })],
  ];
  return (
    <dl className="market-scan__coverage" aria-label={t('discovery.coverage.title')}>
      {rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
    </dl>
  );
}

export function MarketScan() {
  const { t, locale } = useI18n();
  const navigate = useNavigate();
  const status = useDiscoveryStatus();
  const start = useStartDiscovery();
  const [startedRunId, setStartedRunId] = useState(null);
  const runId = startedRunId || status.data?.last_run?.run_id;
  const run = useDiscoveryRun(runId);
  const number = new Intl.NumberFormat(locale);
  const when = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' });

  if (status.isPending) return <Panel><StateBlock kind="loading" compact title={t('common.loading')} /></Panel>;
  if (status.isError) return <Panel><StateBlock kind="error" compact title={t('discovery.error')} onRetry={() => status.refetch()} retryLabel={t('demandApex.actions.retry')} /></Panel>;

  const info = status.data;
  const lastRun = run.data || info.last_run;
  // A scan that failed only for lack of a location is history once a location is set.
  const latest = lastRun?.error === 'no_location' && info.location.has_location ? null : lastRun;
  const active = latest && RUN_ACTIVE.includes(latest.status);
  const connected = info.providers.filter((p) => p.configured).length;
  const providers = [...info.providers].sort((a, b) => PROVIDER_ORDER.indexOf(a.provider) - PROVIDER_ORDER.indexOf(b.provider));
  const industry = info.industry.label[locale?.startsWith('ar') ? 'ar' : 'en'];
  const place = info.location.city || (info.location.latitude != null ? t('discovery.pinnedLocation') : null);

  const onScan = () => start.mutate({}, { onSuccess: (data) => setStartedRunId(data.run_id) });

  let outcome = null;
  if (active) outcome = <p className="market-scan__progress" role="status"><span className="apex-spinner" aria-hidden="true" />{t('discovery.running')}</p>;
  else if (latest?.status === 'failed') {
    const reason = { no_location: 'noLocation', location_not_found: 'locationNotFound', no_sources: 'noSources', unreachable: 'unreachable' }[latest.error] || 'generic';
    outcome = <p className="market-scan__note is-error" role="alert">{t(`discovery.failed.${reason}`)}</p>;
  } else if (latest) {
    outcome = (
      <p className="market-scan__note">
        {t('discovery.result', { found: number.format(latest.found_count), added: number.format(latest.new_count), tracked: number.format(latest.tracked_count) })}
        {latest.finished_at && <span className="apex-muted"> · {when.format(new Date(latest.finished_at))}</span>}
        {latest.status === 'partial' && <span className="apex-muted"> · {t('discovery.partial')}</span>}
        {latest.sources_checked > 0 && (
          <span className="market-scan__checked">{t('discovery.sourcesChecked', { checked: number.format(latest.sources_checked), answered: number.format(latest.sources_answered || 0) })}</span>
        )}
      </p>
    );
  }

  return (
    <Panel
      className="market-scan"
      eyebrow={t('discovery.eyebrow')}
      title={t('discovery.title')}
      subtitle={t('discovery.subtitle', { industry, place: place || t('discovery.noPlace'), radius: number.format(info.radius_km) })}
      actions={(
        <>
          <ApexButton variant="ghost" icon={MapPin} onClick={() => navigate(routePaths.marketSearchScope)}>{t('discovery.changeArea')}</ApexButton>
          <ApexButton icon={latest ? RefreshCw : Radar} loading={start.isPending || active} disabled={!connected} onClick={onScan}>
            {latest ? t('discovery.rescan') : t('discovery.scan')}
          </ApexButton>
        </>
      )}
    >
      <div className="market-scan__providers">
        {providers.map((provider) => <ProviderChip key={provider.provider} t={t} provider={provider} result={!active && latest?.providers?.[provider.provider]} />)}
      </div>
      {!info.location.has_location && <p className="market-scan__note is-warning">{t('discovery.needLocation')} <button type="button" className="apex-table__link" onClick={() => navigate(routePaths.marketSearchScope)}>{t('discovery.setLocation')}</button></p>}
      {start.isError && <p className="market-scan__note is-error" role="alert">{t('discovery.startFailed')}</p>}
      {outcome}
      {!active && <Coverage coverage={latest?.coverage} t={t} number={number} />}
      <p className="apex-source">{t('discovery.provenance')}</p>
    </Panel>
  );
}

export default MarketScan;
