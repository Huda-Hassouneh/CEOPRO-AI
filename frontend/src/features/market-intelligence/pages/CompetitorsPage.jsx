import {COMPETITOR_AI_ACTIONS_ENABLED} from '../config/competitorCapabilities.js';
import { CompetitorConfirmation } from '../components/CompetitorConfirmation.jsx';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { competitorsApi } from '../api/competitorsApi.js';
import { useMemo, useState } from "react";
import { Building2, Radio, ListFilter, Plus, Search } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { getApiErrorMessage } from "../../../shared/lib/apiErrors.js";
import { DashboardLayout } from "../../../app/layouts/DashboardLayout.jsx";
import PageHeader from "../../../shared/components/layout/PageHeader.jsx";
import Button from "../../../shared/components/ui/Button.jsx";
import RecordSummary from '../../../shared/components/ui/RecordSummary.jsx';
import Select from '../../../shared/components/ui/Select.jsx';
import '../styles/CompetitorDirectory.css';
import Input from "../../../shared/components/ui/Input.jsx";
import Skeleton from "../../../shared/components/ui/Skeleton.jsx";
import EmptyState from "../../../shared/components/ui/EmptyState.jsx";
import { routePaths } from "../../../app/router/routePaths.js";
import { MarketTabs } from "../components/MarketTabs.jsx";
import { CompetitorTable } from "../components/CompetitorTable.jsx";
import { useCompetitors } from "../hooks/useCompetitors.js";
import "../styles/MarketIntelligence.css";

export function CompetitorsPage() {
  const { t, locale } = useI18n();
  const navigate = useNavigate();
  const cache=useQueryClient();
  const [discoveryNotice,setDiscoveryNotice]=useState('');
  const discovery=useMutation({mutationFn:()=>competitorsApi.discover(),onSuccess:result=>{setDiscoveryNotice(t(!result.configured?'competitorManagement.pipelineNotConfigured':result.eventId?'competitorManagement.discoveryQueued':'competitorManagement.noCatalogProducts'));}});
  const [confirm,setConfirm]=useState(null);
  const tracking=useMutation({mutationFn:row=>competitorsApi.track(row.id,!row.isTracked),onSuccess:async()=>{await Promise.all([cache.invalidateQueries({queryKey:['competitors']}),cache.invalidateQueries({queryKey:['competitor-profile']}),cache.invalidateQueries({queryKey:['subscription','usage']})]);setConfirm(null);}});
  const [status, setStatus] = useState(COMPETITOR_AI_ACTIONS_ENABLED ? "active" : "all");
  const { data, isLoading, isError, error, refetch } = useCompetitors(status);
  const rows = data?.competitors ?? [];

  const [query, setQuery] = useState("");
  const [industry, setIndustry] = useState("all");
  const [sort, setSort] = useState("updated");
  const [page, setPage] = useState(1);

  const filteredRows = useMemo(() => {
    if (!rows.length) return [];

    const next = rows.filter(
      (row) =>
        (!query ||
          `${row.name} ${row.website}`
            .toLowerCase()
            .includes(query.trim().toLowerCase())) &&
        (industry === "all" || row.industry === industry)
    );

    return sort === "name"
      ? [...next].sort((a, b) => a.name.localeCompare(b.name))
      : [...next].sort((a, b) => new Date(b.addedAt) - new Date(a.addedAt));
  }, [rows, query, industry, sort]);

  const currentPage = Math.min(page, Math.max(1, Math.ceil(filteredRows.length / 10)));
  const visibleRows = filteredRows.slice((currentPage - 1) * 10, currentPage * 10);

  return (
    <DashboardLayout>
      <div className="market-page competitors-page">
        <PageHeader
          title={t("market.competitorsPage.title")}
          subtitle={t("market.competitorsPage.subtitle")}
          actions={COMPETITOR_AI_ACTIONS_ENABLED && data?.canEdit && data?.capacity?.included ?
            <Button
              size="sm"
              leadingIcon={<Plus size={15} />}
              onClick={() => navigate(routePaths.marketAddCompetitor)}
            >
              {t("market.controls.addCompetitor")}
            </Button> : null
          }
        />
        <MarketTabs />
        {!isError && <RecordSummary items={[
          {label:t('directoryUx.competitorsInView'),value:isLoading ? undefined : rows.length,icon:<Building2 size={21} />,hint:t('directoryUx.loadedScope')},
          ...(COMPETITOR_AI_ACTIONS_ENABLED ? [{label:t('directoryUx.trackedInView'),value:isLoading ? undefined : rows.filter(row=>row.isTracked).length,icon:<Radio size={21} />,hint:t('directoryUx.trackingHint')}] : []),
          {label:t('directoryUx.matchingResults'),value:isLoading ? undefined : filteredRows.length,icon:<ListFilter size={21} />,hint:t('directoryUx.filteredHint')}
        ]} />}
        {COMPETITOR_AI_ACTIONS_ENABLED && data?.canEdit && data?.capacity?.included && <div className="competitor-discovery-controls">
          <Button variant="outline" disabled={discovery.isPending} onClick={()=>{setDiscoveryNotice('');discovery.mutate();}}>{t(discovery.isPending?'competitorManagement.saving':'competitorManagement.discoverCatalog')}</Button>
          <p>{t('competitorManagement.discoveryScopeNotice')}</p>
        </div>}
        {COMPETITOR_AI_ACTIONS_ENABLED && discoveryNotice && <p className="competitor-feedback competitor-feedback--success" role="status">{discoveryNotice}</p>}
        {COMPETITOR_AI_ACTIONS_ENABLED && discovery.error && <p className="competitor-feedback competitor-feedback--error" role="alert">{getApiErrorMessage(discovery.error,t)}</p>}
        {COMPETITOR_AI_ACTIONS_ENABLED && data?.capacity && <p>{t('competitorManagement.capacity', { used: data.capacity.currentUsage, limit: data.capacity.isUnlimited ? t('competitorManagement.unlimited') : data.capacity.limit ?? 0 })}</p>}
        {COMPETITOR_AI_ACTIONS_ENABLED && !data?.capacity?.included && data && <p>{t('competitorManagement.cleanupNotice')}</p>}
        <div className="competitor-filters">
          <Input label={t('market.competitorsPage.search')} value={query} onChange={event=>{setQuery(event.target.value);setPage(1);}} placeholder={t('market.competitorsPage.search')} leftIcon={<Search size={17} />} />
          <Select label={t('market.competitorsPage.industry')} value={industry} onChange={event=>{setIndustry(event.target.value);setPage(1);}} options={[{value:'all',label:t('market.competitorsPage.allIndustries')},...[...new Set(rows.map(row=>row.industry).filter(Boolean))].sort().map(value=>({value,label:value}))]} />
          <Select label={t('market.competitorsPage.sort')} value={sort} onChange={event=>{setSort(event.target.value);setPage(1);}} options={[{value:'updated',label:t('directoryUx.newestAdded')},{value:'name',label:t('market.competitorsPage.name')}]} />
          {COMPETITOR_AI_ACTIONS_ENABLED && <Select label={t('competitorManagement.status')} value={status} onChange={event=>{setStatus(event.target.value);setPage(1);}} options={['active','inactive','all'].map(value=>({value,label:t(`competitorManagement.${value}`)}))} />}
        </div>
        {(query || industry!=='all') && <div className="directory-filter-feedback"><span>{t('directoryUx.filteredHint')}</span><Button variant="ghost" size="sm" onClick={()=>{setQuery('');setIndustry('all');setPage(1);}}>{t('directoryUx.clearFilters')}</Button></div>}


        <CompetitorConfirmation open={Boolean(confirm)} t={t} locale={locale} name={confirm?.name}
          message={t(confirm?.isTracked ? 'competitorManagement.confirmUntrack' : 'competitorManagement.confirmReactivate')}
          destructive={Boolean(confirm?.isTracked)} busy={tracking.isPending}
          error={tracking.error && getApiErrorMessage(tracking.error,t)}
          onCancel={()=>setConfirm(null)} onConfirm={()=>tracking.mutate(confirm)} />
        <section className="market-panel competitor-list-panel">
          {isLoading ? (
            <div className="market-main-loading" style={{ padding: "2rem" }}>
              <Skeleton height="300px" variant="rectangular" />
            </div>
          ) : isError ? (
            <EmptyState
              title={t("market.competitorsPage.errorTitle", "Could not load competitors")}
              description={getApiErrorMessage(error, t)}
              action={<Button onClick={() => refetch()}>{t("common.retry")}</Button>}
            />
          ) : (
            <>
              <CompetitorTable
                t={t}
                locale={locale}
                filtered={Boolean(query || industry!=='all')}
                rows={visibleRows}
                canEdit={COMPETITOR_AI_ACTIONS_ENABLED && data?.canEdit}
                canReactivate={data?.capacity?.included}
                busy={tracking.isPending}
                onTrack={row=>{tracking.reset();setConfirm(row);}}
                onDetails={(id) =>
                  navigate(`${routePaths.marketCompetitors}/${id}`)
                }
              />
              <div className="competitor-pagination">
                <span>
                  {t("market.competitorsPage.showing", {
                    start: filteredRows.length ? (currentPage - 1) * 10 + 1 : 0,
                    end: Math.min(currentPage * 10, filteredRows.length),
                    total: filteredRows.length
                  })}
                </span>
                <div>
                  <button
                    type="button"
                    disabled={currentPage === 1}
                    onClick={() => setPage(currentPage - 1)}
                    aria-label={t("market.competitorsPage.previous")}
                  >
                    ‹
                  </button>
                  <button
                    type="button"
                    className="is-current"
                    aria-current="page"
                  >
                    {currentPage}
                  </button>
                  <button
                    type="button"
                    disabled={currentPage * 10 >= filteredRows.length}
                    onClick={() => setPage(currentPage + 1)}
                    aria-label={t("market.competitorsPage.next")}
                  >
                    ›
                  </button>
                </div>
              </div>
            </>
          )}
        </section>
      </div>
    </DashboardLayout>
  );
}
