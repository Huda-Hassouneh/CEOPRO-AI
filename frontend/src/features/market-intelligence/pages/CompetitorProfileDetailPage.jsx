import {COMPETITOR_AI_ACTIONS_ENABLED} from '../config/competitorCapabilities.js';
import {collectionState} from '../utils/collectionStatus.js';
import {CompetitorProductLinks} from '../components/CompetitorProductLinks.jsx';
import {DiscoveryCoverage} from '../components/DiscoveryCoverage.jsx';
import {CompetitorSourceReviews} from '../components/CompetitorSourceReviews.jsx';
import {discoveryState} from '../utils/discoveryStatus.js';
import Button from '../../../shared/components/ui/Button.jsx';
import Input from '../../../shared/components/ui/Input.jsx';
import { PauseCircle, PlayCircle, Clock3, Info, ExternalLink, Package, CheckCircle2, ShieldCheck } from 'lucide-react';
import { CompetitorConfirmation } from '../components/CompetitorConfirmation.jsx';
import { useEffect, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { competitorsApi } from '../api/competitorsApi.js';
import { useAuthStore } from '../../auth/store/authStore.js';
import { useNavigate, useParams } from "react-router-dom";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { getApiErrorMessage } from "../../../shared/lib/apiErrors.js";
import { DashboardLayout } from "../../../app/layouts/DashboardLayout.jsx";
import RecordSummary from '../../../shared/components/ui/RecordSummary.jsx';
import '../styles/CompetitorDirectory.css';
import Card from "../../../shared/components/ui/Card.jsx";
import Skeleton from "../../../shared/components/ui/Skeleton.jsx";
import EmptyState from "../../../shared/components/ui/EmptyState.jsx";
import { CompetitorDetailHeader } from "../components/CompetitorDetailSections.jsx";
import { useCompetitorProfile } from "../hooks/useCompetitorProfile.js";
import "../styles/MarketIntelligence.css";

export function CompetitorProfileDetailPage() {
  const { t, locale } = useI18n();
  const navigate = useNavigate();
  const { competitorId } = useParams();
  const tenantId = useAuthStore(state => state.tenantId);
  const cache = useQueryClient();
  const [alias,setAlias] = useState('');
  const [notice,setNotice] = useState('');
  const [confirmation,setConfirmation] = useState(null);
  const mutation=useMutation({mutationFn: async action => {
    if (action.type==='cancelDiscovery') return competitorsApi.cancelDiscovery(competitorId,action.eventId);
    if (action.type==='alias') return competitorsApi.update(competitorId,action.alias || null);
    if (action.type==='tracking') return competitorsApi.track(competitorId,action.tracked);
    if (action.type==='mapping') return competitorsApi.confirm(competitorId,action.mappingId,action.confirmed);
    return competitorsApi.schedule(competitorId);
  },onSuccess: async (result,_action) => {
    if (_action.type==='schedule') setNotice(result.reason ? t(`competitorManagement.${result.reason}`) : t(result.configured?'competitorManagement.scheduleQueued':'competitorManagement.scheduleAwaitingSetup',{count:result.updatedSources,queued:result.queuedSources ?? 0}));
    await Promise.all([cache.invalidateQueries({queryKey:['competitors',tenantId]}),cache.invalidateQueries({queryKey:['competitor-profile',tenantId,competitorId]}),cache.invalidateQueries({queryKey:['subscription','usage']})]);
    setConfirmation(null);
  }});
  useEffect(()=>{setConfirmation(null);setAlias('');setNotice('');mutation.reset();},[tenantId,competitorId]);

  const {
    data: detail,
    isLoading,
    isError,
    error
  } = useCompetitorProfile(competitorId);

  useEffect(()=>{setAlias(detail?.alias ?? detail?.name ?? '');},[detail?.alias,detail?.name]);
  const run = action => {setNotice('');mutation.mutate(action);};
  const formatDate = (dateString) => {
    if (!dateString || !Number.isFinite(new Date(dateString).getTime())) return '—';
    return new Intl.DateTimeFormat(locale, {
      month: "short",
      day: "numeric",
      year: "numeric"
    }).format(new Date(dateString));
  };

  const getLocalizedName = (nameObj) =>
    typeof nameObj === "string" ? nameObj : nameObj?.[locale] || nameObj?.en || "—";

  if (isLoading) {
    return (
      <DashboardLayout>
        <div className="market-page competitor-detail-page">
          <Skeleton height="150px" variant="rectangular" />
          <Skeleton
            height="300px"
            variant="rectangular"
            style={{ marginTop: "1rem" }}
          />
        </div>
      </DashboardLayout>
    );
  }

  if (isError || !detail) {
    return (
      <DashboardLayout>
        <EmptyState
          title={t("market.detail.loadErrorTitle", "Could not load competitor")}
          description={getApiErrorMessage(error, t)}
          action={
            <Button variant="outline" onClick={() => navigate("/market/competitors")}>
              {t("market.detail.back")}
            </Button>
          }
        />
      </DashboardLayout>
    );
  }

  return (
    <DashboardLayout>
      <div className="market-page competitor-detail-page">
        <CompetitorDetailHeader
          t={t}
          detail={detail}
          onBack={() => navigate("/market/competitors")}
        />

        <RecordSummary items={[
          {label:t('directoryUx.mappedProducts'),value:detail.mappedProducts.length,icon:<Package size={21} />,hint:t('directoryUx.mappingsHint')},
          ...(COMPETITOR_AI_ACTIONS_ENABLED ? [{label:t('directoryUx.confirmedProducts'),value:detail.mappedProducts.filter(item=>item.comparisonConfirmed).length,icon:<CheckCircle2 size={21} />,hint:t('directoryUx.confirmedHint')},
          {label:t('directoryUx.approvedSources'),value:(detail.sources ?? []).filter(source=>source.isActive && source.policyStatus==='ALLOWED').length,icon:<ShieldCheck size={21} />,hint:t('directoryUx.approvalHint')}] : [])
        ]} />

        {detail.canEdit && <section className="market-panel competitor-management-panel">
          <div className="competitor-management-panel__heading"><h2>{t('competitorManagement.settings')}</h2><p>{t('competitorManagement.settingsHint')}</p></div>
          <div className="competitor-management-panel__body">
            <form className="competitor-alias-form" onSubmit={event=>{event.preventDefault();run({type:'alias',alias:alias.trim()});}}>
              <Input label={t('competitorManagement.alias')} value={alias} maxLength={255} onChange={event=>setAlias(event.target.value)} disabled={mutation.isPending} />
              <Button type="submit" disabled={mutation.isPending}>{t('competitorManagement.saveAlias')}</Button>
            </form>
            {COMPETITOR_AI_ACTIONS_ENABLED && <div className="competitor-management-actions">
              <Button variant="outline" className={detail.isTracked ? 'competitor-button--danger-outline' : ''} disabled={mutation.isPending}
                leadingIcon={detail.isTracked ? <PauseCircle size={17} /> : <PlayCircle size={17} />}
                onClick={()=>{mutation.reset();setConfirmation({type:'tracking',tracked:!detail.isTracked});}}>{t(detail.isTracked?'competitorManagement.untrack':'competitorManagement.reactivate')}</Button>
              {detail.isTracked && <Button variant="outline" disabled={mutation.isPending} leadingIcon={<Clock3 size={17} />} onClick={()=>run({type:'schedule'})}>{t('competitorManagement.applySchedule')}</Button>}
            </div>}
          </div>
        </section>}
        <CompetitorConfirmation open={Boolean(confirmation)} t={t} locale={locale} name={detail.name}
          message={t(confirmation?.type==='mapping'?'competitorManagement.confirmMapping':confirmation?.tracked?'competitorManagement.confirmReactivate':'competitorManagement.confirmUntrack')}
          destructive={confirmation?.type==='tracking' && !confirmation?.tracked} busy={mutation.isPending}
          error={mutation.error && getApiErrorMessage(mutation.error,t)}
          onCancel={()=>setConfirmation(null)} onConfirm={()=>run(confirmation)} />
        {mutation.error && !confirmation && <p className="competitor-feedback competitor-feedback--error" role="alert">{getApiErrorMessage(mutation.error,t)}</p>}
        {notice && <p className="competitor-feedback competitor-feedback--success" role="status">{notice}</p>}
        {COMPETITOR_AI_ACTIONS_ENABLED && detail.trackingIntegration && <section className="market-panel competitor-pipeline-status">
          <h2>{t('competitorManagement.pipelineTitle')}</h2>
          <p>{t(detail.trackingIntegration.configured?'competitorManagement.pipelineConfigured':'competitorManagement.pipelineNotConfigured')}</p>
          <p>{t('competitorManagement.discoveryScopeNotice')}</p>
          {detail.trackingIntegration.events.map((event,index)=><div className="competitor-pipeline-event" key={`${event.created_at}-${index}`}>
            <strong>{t(event.kind==='DISCOVERY'?(event.competitor_id?'competitorManagement.competitorDiscoveryJob':'competitorManagement.discoveryJob'):'competitorManagement.collectionJob')}</strong>
            <span>{event.kind==='DISCOVERY'?t(`competitorManagement.discoveryStates.${discoveryState(event)}`):t(`collectionTracking.states.${collectionState(event)}`)}</span>
            {event.kind==='DISCOVERY' && event.worker_result?.stage && discoveryState(event)==='RUNNING' && <small>{t('competitorManagement.currentStep',{step:event.worker_result.stage})}</small>}
            {event.kind==='DISCOVERY' && event.worker_result && Number.isInteger(event.worker_result.product_level_candidates) && <small>{t('competitorManagement.discoveryResults',{products:event.worker_result.product_level_candidates,domains:event.worker_result.domain_level_candidates ?? 0,sources:event.worker_result.enqueued_source_ids?.length ?? 0})}</small>}
            {detail.canEdit && event.kind==='DISCOVERY' && ['QUEUED','RUNNING','INTERRUPTED'].includes(discoveryState(event)) && <Button variant="secondary" disabled={mutation.isPending} onClick={()=>run({type:'cancelDiscovery',eventId:event.event_id})}>{t('competitorManagement.cancelDiscovery')}</Button>}
            <small>{formatDate(event.created_at)}</small>
            {event.kind==='DISCOVERY' && event.worker_result?.access_issues?.slice(0,3).map((issue,i)=><small key={`access-${i}`}>{issue.host}: {t(`competitorManagement.workerErrors.${issue.code}`)}{issue.http_status ? ` (HTTP ${issue.http_status})` : ''}</small>)}
            {event.kind==='DISCOVERY' && <DiscoveryCoverage result={event.worker_result} t={t} />}
            {event.kind==='DISCOVERY' && event.worker_error_code && <small>{t(`competitorManagement.workerErrors.${event.worker_error_code}`)}</small>}
            {event.kind==='COLLECTION' && event.worker_error_code && <small>{t(`collectionTracking.errors.${event.worker_error_code}`)}</small>}
            {event.last_error_code && <small>{t(`competitorManagement.bridgeErrors.${event.last_error_code}`)}</small>}
          </div>)}
        </section>}
        <CompetitorProductLinks key={`links:${tenantId}:${competitorId}`} detail={detail} tenantId={tenantId} competitorId={competitorId} t={t} locale={locale} />
        <CompetitorSourceReviews key={`${tenantId}:${competitorId}`} detail={detail} tenantId={tenantId} competitorId={competitorId} t={t} locale={locale} formatDate={formatDate} />
        {COMPETITOR_AI_ACTIONS_ENABLED && <div className="competitor-info-note"><Info size={18} aria-hidden="true" /><p>{t('competitorManagement.addNotice')}</p></div>}

        <section
          className="market-panel competitor-products"
          id="competitor-products"

        >
          <div className="market-panel__header">
            <div>
              <h2>{t("market.detail.productsTitle", "Mapped Products")}</h2>
              <p>
                {t(
                  "market.detail.productsSubtitle",
                  "Your products tracked against this competitor"
                )}
              </p>
            </div>
          </div>

          <div className="market-table-wrap">
            <table className="market-table">
              <thead>
                <tr>
                  <th>{t("market.detail.productName", "Product")}</th>
                  <th>{t("market.detail.ourPrice", "Our Price")}</th>
                  <th>
                    {t("market.detail.competitorPrice", "Competitor Price")}
                  </th>
                  <th>{t("market.detail.lastUpdated", "Last Checked")}</th>
                  <th>{t('competitorManagement.comparisonStatus')}</th>
                </tr>
              </thead>
              <tbody>
                {detail.mappedProducts.length === 0 ? (
                  <tr>
                    <td
                      colSpan="5"
                      style={{ textAlign: "center", padding: "2rem" }}
                    >
                      {t("competitorManagement.noMappings")}
                    </td>
                  </tr>
                ) : (
                  detail.mappedProducts.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <strong>{getLocalizedName(item.name)}</strong>
                      </td>
                      <td>
                        {item.ourPrice == null ? '—' : `${item.ourPrice} ${item.currency}`} 
                      </td>
                      <td>
                        {item.competitorPrice == null ? "—" : `${item.competitorPrice} ${item.currency}`}
                        {item.collectedPrice && item.reason && <small className="competitor-source-meta">{t('competitorWorkflow.lastCollected')}: {item.collectedPrice.amount} {item.collectedPrice.currency} · {formatDate(item.collectedPrice.observedAt)}</small>}
                      </td>
                      <td>{formatDate(item.lastUpdated)}
                        {COMPETITOR_AI_ACTIONS_ENABLED && item.monitoring && <small className="competitor-source-meta">{t('competitorManagement.monitoring',{minutes:item.monitoring.frequencyMinutes ?? '—'})}<br />{t('competitorManagement.lastSync')}: {formatDate(item.monitoring.lastSyncedAt)}{item.monitoring.latestJob && <><br />{t('competitorManagement.collectionJob')}: {t(`competitorManagement.jobs.${['QUEUED','PROCESSING','COMPLETED','FAILED','PARTIAL','EXTRACTING','EXTRACTED','PENDING'].includes(item.monitoring.latestJob.status) ? item.monitoring.latestJob.status : 'UNKNOWN'}`)}</>}</small>}
                      </td>
                      <td><span className={`competitor-comparison-state ${item.reason ? 'is-unavailable' : 'is-available'}`}>{t(item.reason ? `competitorManagement.${item.reason}` : 'competitorManagement.available')}</span>
                        {Number.isFinite(item.priceDifference) && <small className="competitor-price-difference">{t('competitorManagement.difference')}: {item.priceDifference.toFixed(4)} {item.currency}{Number.isFinite(item.priceDifferencePercent) ? ` (${item.priceDifferencePercent.toFixed(1)}%)` : ''}</small>}
                        {COMPETITOR_AI_ACTIONS_ENABLED && detail.canEdit && detail.isTracked && <label className="competitor-mapping-confirmation"><input type="checkbox" checked={item.comparisonConfirmed} disabled={mutation.isPending}
                          onChange={event=>event.target.checked ? (mutation.reset(),setConfirmation({type:'mapping',mappingId:item.mappingId,confirmed:true})) : run({type:'mapping',mappingId:item.mappingId,confirmed:false})} />{t('competitorManagement.mappingConfirmation')}</label>}
                        {item.url && <a className="competitor-product-link" href={item.url} target="_blank" rel="noopener noreferrer"><ExternalLink size={14} aria-hidden="true" />{t('market.modal.website')}</a>}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section
          className="competitor-activity-section"
        >
          <Card className="market-panel">
            <div className="market-panel__header">
              <h2>
                {t("market.detail.recentActivity", "Recent Price Changes")}
              </h2>
            </div>
            <div className="strategic-moves">
              {detail.activity.length === 0 ? (
                <p style={{ padding: "1rem 0" }}>
                  {t("competitorManagement.noActivity")}
                </p>
              ) : (
                detail.activity.map((item) => (
                  <div key={item.id} className="competitor-activity-row">
                    <span className={`competitor-activity-dot ${item.newPrice > item.previousPrice ? 'is-up' : 'is-down'}`} aria-hidden="true" />
                    <strong className="competitor-activity-product">
                      {getLocalizedName(item.productName)}
                      <small>
                        {t("competitorManagement.priceChanged",{old:item.previousPrice,new:item.newPrice,currency:item.currency})}
                      </small>
                    </strong>
                    <small className="competitor-activity-date">{formatDate(item.date)}</small>
                  </div>
                ))
              )}
            </div>
          </Card>
        </section>
      </div>
    </DashboardLayout>
  );
}
