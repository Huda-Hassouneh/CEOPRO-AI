import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, ArrowRight, Newspaper, Radar } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { ApexButton, Panel, Pill, StateBlock } from '../../../shared/components/apex/Apex.jsx';
import httpClient from '../../../shared/lib/httpClient.js';
import { describeAlert, ICONS } from '../../alerts/AlertsBell.jsx';
import { useCampaigns } from '../../marketing/hooks/useCampaigns.js';
import { discoveryApi } from '../../market-intelligence/api/discoveryApi.js';
import { safeHref } from '../../../shared/lib/safeUrl.js';

const CAMPAIGN_TONE = { COMPLETED: 'success', FAILED: 'danger', PENDING: 'neutral', DRAFT: 'neutral', SCHEDULED: 'violet', PUBLISHED: 'success' };

// The dashboard's activity row: the latest campaigns, what competitor
// discovery last found (and news), and recent updates - each from live
// data, with a next step when there is nothing yet.
export function DashboardActivity() {
  const { t, locale } = useI18n();
  const navigate = useNavigate();
  const date = useMemo(() => new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }), [locale]);
  const number = useMemo(() => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }), [locale]);
  const money = (value, currency) => { try { return new Intl.NumberFormat(locale, { style: 'currency', currency }).format(value); } catch { return String(value); } };
  const campaigns = useCampaigns({ limit: 4 });
  const discovery = useQuery({ queryKey: ['discovery-status'], queryFn: discoveryApi.status });
  const news = useQuery({ queryKey: ['discovery-news', 'dashboard'], queryFn: () => discoveryApi.news({ limit: 3 }) });
  const alerts = useQuery({ queryKey: ['alerts'], queryFn: async () => (await httpClient.get('/alerts')).data, staleTime: 2 * 60_000 });
  const lastRun = discovery.data?.last_run;
  const go = (to) => <ApexButton size="sm" variant="ghost" onClick={() => navigate(to)}>{t('dashboardActivity.open')}<ArrowRight size={14} className="apex-flip-rtl" /></ApexButton>;

  return (
    <div className="apex-grid apex-grid--3">
      <Panel eyebrow={t('dashboardActivity.campaigns.eyebrow')} title={t('dashboardActivity.campaigns.title')} actions={go(routePaths.marketing)}>
        {campaigns.isPending ? <StateBlock kind="loading" compact title={t('common.loading')} />
          : campaigns.isError ? <StateBlock kind="error" compact title={t('dashboardActivity.loadError')} onRetry={() => campaigns.refetch()} retryLabel={t('demandApex.actions.retry')} />
            : campaigns.data?.campaigns?.length ? (
              <>
                <p className="apex-muted cc-activity__count">{t('dashboardActivity.campaigns.total', { count: campaigns.data.total })}</p>
                <ul className="cc-list">
                  {campaigns.data.campaigns.map((c) => (
                    <li key={c.campaign_id}>
                      <div>
                        <button type="button" className="apex-table__link" dir="auto" onClick={() => navigate(`${routePaths.marketing}?campaign=${c.campaign_id}`)}>{c.campaign_brief}</button>
                        {c.requested_at && <span className="apex-muted">{date.format(new Date(c.requested_at))}</span>}
                      </div>
                      <Pill tone={CAMPAIGN_TONE[c.status] || 'neutral'}>{t(`marketingApex.history.status.${c.status}`, { defaultValue: c.status })}</Pill>
                    </li>
                  ))}
                </ul>
              </>
            ) : <StateBlock compact title={t('dashboardActivity.campaigns.empty')} description={t('dashboardActivity.campaigns.emptyHint')}
              action={<ApexButton size="sm" onClick={() => navigate(routePaths.marketing)}>{t('dashboardActivity.campaigns.create')}</ApexButton>} />}
      </Panel>

      <Panel eyebrow={t('dashboardActivity.market.eyebrow')} title={t('dashboardActivity.market.title')} actions={go(routePaths.market)}>
        {discovery.isPending ? <StateBlock kind="loading" compact title={t('common.loading')} />
          : !lastRun ? (
            <StateBlock compact title={t('dashboardActivity.market.never')} description={t('dashboardActivity.market.neverHint')}
              action={<ApexButton size="sm" icon={Radar} onClick={() => navigate(routePaths.market)}>{t('dashboardActivity.market.scan')}</ApexButton>} />
          ) : (
            <>
              <p className="cc-activity__line">
                {lastRun.status === 'failed'
                  ? <span className="is-error"><AlertTriangle size={13} aria-hidden="true" /> {t('dashboardActivity.market.failed')}</span>
                  : t('dashboardActivity.market.result', { found: number.format(lastRun.found_count), added: number.format(lastRun.new_count) })}
                {lastRun.finished_at && <span className="apex-muted"> · {date.format(new Date(lastRun.finished_at))}</span>}
              </p>
              {news.data?.length > 0 ? (
                <ul className="intel-news">
                  {news.data.map((a) => (
                    <li key={a.url}><Newspaper size={14} aria-hidden="true" />
                      <div><a href={safeHref(a.url)} target="_blank" rel="noreferrer noopener" dir="auto">{a.title}</a>
                        <div className="apex-muted">{[a.source_domain, a.published_at && date.format(new Date(a.published_at))].filter(Boolean).join(' · ')}</div></div>
                    </li>
                  ))}
                </ul>
              ) : <p className="apex-muted">{t('intel.noNewsYet')}</p>}
            </>
          )}
      </Panel>

      <Panel eyebrow={t('dashboardActivity.updates.eyebrow')} title={t('dashboardActivity.updates.title')}>
        {alerts.isPending ? <StateBlock kind="loading" compact title={t('common.loading')} />
          : alerts.isError ? <StateBlock kind="error" compact title={t('alerts.error')} onRetry={() => alerts.refetch()} retryLabel={t('demandApex.actions.retry')} />
            : alerts.data?.alerts?.length ? (
              <ul className="cc-updates">
                {alerts.data.alerts.slice(0, 5).map((a) => {
                  const Icon = (ICONS[a.kind] || (() => AlertTriangle))(a);
                  return (
                    <li key={a.id}>
                      <button type="button" className={`apex-alerts__item is-${a.severity}`} onClick={() => navigate(a.link)}>
                        <Icon size={16} aria-hidden="true" /><span>{describeAlert(a, t, number, money)}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            ) : <StateBlock compact title={t('alerts.empty')} />}
      </Panel>
    </div>
  );
}

export default DashboardActivity;
