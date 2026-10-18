import ShopifyPrivacyReports from '../components/ShopifyPrivacyReports.jsx';
import WebsiteStoreSetup, {storeErrorMessage} from "../components/WebsiteStoreSetup.jsx";
import { getApiError } from "../../../shared/lib/apiErrors.js";
import { activityTypeLabel, activityName, dataCategoryLabel, importSheetLabel, localizedConnectionValue, dataConnectionErrorMessage } from '../utils/connectionPresentation.js';
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  BarChart3,
  Building2,
  Check,
  Download,
  FileText,
  Link2,
  Plus
} from "lucide-react";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { useAuthStore } from "../../auth/store/authStore.js";
import PageHeader from "../../../shared/components/layout/PageHeader.jsx";
import Button from "../../../shared/components/ui/Button.jsx";
import EmptyState from "../../../shared/components/ui/EmptyState.jsx";
import Modal from "../../../shared/components/ui/Modal.jsx";
import Skeleton from "../../../shared/components/ui/Skeleton.jsx";
import Toast from "../../../shared/components/ui/Toast.jsx";
import { FileUploadDropzone } from "../../data-ingestion/components/FileUploadDropzone.jsx";
import { StructuredImportReview } from "../../data-ingestion/components/StructuredImportReview.jsx";
import { IngestionJobStatusTable } from "../../data-ingestion/components/IngestionJobStatusTable.jsx";
import { StagingRowReviewGrid } from "../../data-ingestion/components/StagingRowReviewGrid.jsx";
import { getDataTemplateOptions } from "../../data-ingestion/config/dataTemplateOptions.js";
import { ingestionApi } from "../../data-ingestion/api/ingestionApi.js";
import { formatImportIssue } from "../../data-ingestion/utils/importIssueMessage.js";
import { DataSourceCard } from "../components/DataSourceCard.jsx";
import { ConnectedSourceCard } from "../components/ConnectedSourceCard.jsx";
import { ConnectionStatusBadge } from "../components/ConnectionStatusBadge.jsx";
import { DATA_SOURCE_ASSETS } from "../config/providerAssets.js";
import { dataConnectionsApi } from "../api/dataConnectionsApi.js";
import { useDataConnections } from "../hooks/useDataConnections.js";
import { FeatureGate } from "../../billing/components/FeatureGate.jsx";
import "../styles/DataConnections.css";
import "../../data-ingestion/styles/DataIngestion.css";
import "../styles/ConnectDataPage.css";

const sourceIcons = {
  analytics: <img src={DATA_SOURCE_ASSETS.googleAnalytics} alt="" />,
  website: <Link2 size={27} />,
  businessSystem: <Building2 size={27} />,
  documents: <FileText size={27} />
};

export function ConnectDataPage() {
  const { t, locale, dir } = useI18n();
  const companyId = useAuthStore((state) => state.tenantId);
  const query = useDataConnections(companyId);
  const queryClient = useQueryClient();

  const [addOpen, setAddOpen] = useState(false);
  const [detailSource, setDetailSource] = useState(null);
  const [detailJob, setDetailJob] = useState(null);
  const [disconnectSource, setDisconnectSource] = useState(null);
  const [detailJobRows, setDetailJobRows] = useState([]);
  const [detailJobPage, setDetailJobPage] = useState(1);
  const [detailJobTotal, setDetailJobTotal] = useState(0);
  const [jobBusy, setJobBusy] = useState(false);
  const [files, setFiles] = useState([]);
  const [importKind, setImportKind] = useState("sales");
  const [importBusy, setImportBusy] = useState(false);
  const [importPreview, setImportPreview] = useState(null);
  const [productChoices, setProductChoices] = useState({});
  const [importReview, setImportReview] = useState(null);
  const [downloadedTemplates, setDownloadedTemplates] = useState([]);
  const [websiteUrl, setWebsiteUrl] = useState("");
  const [storeSourceId,setStoreSourceId]=useState(null);
  const [storeSetupOpen, setStoreSetupOpen] = useState(false);
  const [busySource, setBusySource] = useState(null);
  const [notice, setNotice] = useState(null);
  useEffect(()=>{
    if(!companyId)return;
    const url=new URL(window.location.href),fragment=new URLSearchParams(url.hash.slice(1));
    const ticket=fragment.get('shopify_ticket'),result=url.searchParams.get('shopify'),errorCode=url.searchParams.get('code');
    if(!ticket&&!result)return;
    const pending=sessionStorage.getItem('keel.shopify.state');
    url.searchParams.delete('shopify');url.searchParams.delete('code');url.hash='';
    window.history.replaceState(null,'',url.pathname+url.search);
    if(ticket){
      sessionStorage.removeItem('keel.shopify.state');
      if(!pending||fragment.get('shopify_state')!==pending){setNotice({variant:'error',message:t('storeConnection.errors.STORE_SHOPIFY_AUTH_EXPIRED')});return;}
      dataConnectionsApi.finishShopify(ticket).then(()=>{setNotice({variant:'success',message:t('storeConnection.shopify.connected')});query.refetch();})
       .catch(error=>setNotice({variant:'error',message:storeErrorMessage(error,t)}));
    }else setNotice({variant:'error',message:storeErrorMessage({response:{data:{code:errorCode||'STORE_SHOPIFY_AUTH_FAILED'}}},t)});
  },[companyId]);
  const uploadRef = useRef(null);

  const number = useMemo(() => new Intl.NumberFormat(locale), [locale]);
  const date = useMemo(
    () =>
      new Intl.DateTimeFormat(locale, {
        dateStyle: "medium",
        timeStyle: "short"
      }),
    [locale]
  );

  const localize = (value) => localizedConnectionValue(value, locale);
  const formatDate = (value) =>
    value ? date.format(new Date(value)) : t("connectData.connected.neverSynced");
  const isSourceCapacityReached =
    !query.data?.sourceCapacity?.isUnlimited &&
    query.data?.sourceCapacity?.remaining != null &&
    query.data.sourceCapacity.remaining <= 0;

  const renderSourceOption = (type) => (
    <DataSourceCard
      key={type}
      icon={sourceIcons[type]}
      title={t(`dataConnections.${type}.title`)}
      description={t(`dataConnections.${type}.description`)}
      actionLabel={t(`dataConnections.${type}.action`)}
      showStatus={false}
      loading={busySource === type}
      actionDisabled={
        (type === "website" && !websiteUrl.trim()) ||
        (type !== "documents" && isSourceCapacityReached)
      }
      onAction={() => connectSource(type)}
    >
      {type === "website" && (
        <input
          className="ceopro-setup-url-input"
          type="url"
          value={websiteUrl}
          onChange={(event) => setWebsiteUrl(event.target.value)}
          placeholder={t("dataConnections.website.placeholder")}
          aria-label={t("dataConnections.website.inputLabel")}
        />
      )}
    </DataSourceCard>
  );

  const goToUpload = () => {
    setAddOpen(false);
    globalThis.setTimeout(
      () =>
        uploadRef.current?.scrollIntoView({
          behavior: "smooth",
          block: "start"
        }),
      0
    );
  };

  const openJobDetails = async (jobId) => {
    setJobBusy(true);
    try {
      const [job, staging] = await Promise.all([
        ingestionApi.getJob(jobId),
        ingestionApi.reviewStagingRows(jobId, { page: 1, pageSize: 50 })
      ]);
      setDetailJob(job);
      setDetailJobRows(staging?.rows ?? []);
      setDetailJobPage(1);
      setDetailJobTotal(staging?.total ?? 0);
    } catch (error) {
      setNotice({ variant: "error", message: dataConnectionErrorMessage(error, t) });
    } finally {
      setJobBusy(false);
    }
  };

  const loadJobStagingPage = async (page) => {
    if (!detailJob) return;
    setJobBusy(true);
    try {
      const staging = await ingestionApi.reviewStagingRows(detailJob.id, {
        page,
        pageSize: 50
      });
      setDetailJobRows(staging?.rows ?? []);
      setDetailJobPage(staging?.page ?? page);
      setDetailJobTotal(staging?.total ?? 0);
    } catch (error) {
      setNotice({ variant: "error", message: dataConnectionErrorMessage(error, t) });
    } finally {
      setJobBusy(false);
    }
  };

  const saveStagingCorrection = async (row, payload) => {
    await ingestionApi.updateStagingRow(detailJob.id, row.id, payload);
    const [job, staging] = await Promise.all([
      ingestionApi.getJob(detailJob.id),
      ingestionApi.reviewStagingRows(detailJob.id, {
        page: detailJobPage,
        pageSize: 50
      })
    ]);
    setDetailJob(job);
    setDetailJobRows(staging?.rows ?? []);
    setDetailJobTotal(staging?.total ?? 0);
    await query.refetch();
  };

  const retrySelectedJob = async () => {
    if (!detailJob) return;
    setJobBusy(true);
    try {
      await ingestionApi.retryJob(detailJob.id);
      setNotice({ variant: "success", message: t("connectData.feedback.retryQueued") });
      const job = await ingestionApi.getJob(detailJob.id);
      setDetailJob(job);
      await query.refetch();
    } catch (error) {
      setNotice({ variant: "error", message: dataConnectionErrorMessage(error, t) });
    } finally {
      setJobBusy(false);
    }
  };

  const runSourceAction = async (action, source) => {
    if(action === "connectStore"){setStoreSourceId(source.provider==='shopify'?source.id:null);setWebsiteUrl(source.sourceUrl);setStoreSetupOpen(true);return;}
    if (action === "details") return setDetailSource(source);
    if (action === "uploadVersion") return goToUpload();
    if (action === "disconnect") return setDisconnectSource(source);

    setBusySource(source.id);
    try {
      if (action === "pause" || action === "reactivate") {
        const updated = await dataConnectionsApi.setActive(
          source.id,
          action === "reactivate"
        );
        if (updated?.isActive !== (action === "reactivate")) {
          throw new Error(t("connectData.feedback.backendUnavailable"));
        }
        setNotice({
          variant: "success",
          message: t(
            action === "pause"
              ? "connectData.feedback.paused"
              : "connectData.feedback.reactivated"
          )
        });
      } else if (action === "syncNow" || action === "retry" && ["woocommerce","shopify"].includes(source.provider)) {
        const sync=await dataConnectionsApi.syncStore(source.id);
        setNotice({variant:"success",message:t(sync.status==="SYNCING"?"storeConnection.alreadySyncing":"storeConnection.syncQueued")});
      } else if (action === "retry" && source.latestJobId) {
        await ingestionApi.retryJob(source.latestJobId);
        setNotice({
          variant: "success",
          message: t("connectData.feedback.retryQueued")
        });
      } else {
        throw new Error(t("connectData.feedback.backendUnavailable"));
      }
      await query.refetch();
    } catch (error) {
      console.error("Action failed:", error);
      setNotice({
        variant: "error",
        message: ["woocommerce","shopify"].includes(source.provider) ? storeErrorMessage(error,t) : dataConnectionErrorMessage(error, t)
      });
    } finally {
      setBusySource(null);
    }
  };

  const confirmDisconnect = async () => {
    if (!disconnectSource) return;
    setBusySource(disconnectSource.id);
    try {
      const result = await (["woocommerce","shopify"].includes(disconnectSource.provider) ? dataConnectionsApi.disconnectStore(disconnectSource.id) : dataConnectionsApi.disconnect(disconnectSource.id));
      if (result?.connectionStatus !== "disconnected" || result?.isActive) {
        throw new Error(t("connectData.feedback.backendUnavailable"));
      }
      setDisconnectSource(null);
      setNotice({
        variant: "success",
        message: t("connectData.feedback.disconnected")
      });
      await query.refetch();
    } catch (error) {
      setNotice({
        variant: "error",
        message: dataConnectionErrorMessage(error, t)
      });
    } finally {
      setBusySource(null);
    }
  };

  const connectSource = async (type) => {
    if (type === "documents") return goToUpload();
    if (type !== "website") {
      setNotice({
        variant: "error",
        message: t("connectData.feedback.backendUnavailable")
      });
      return;
    }
    if (type === "website" && !websiteUrl.trim()) return;

    setAddOpen(false);
    setStoreSourceId(null);
    setStoreSetupOpen(true);
  };

  const downloadTemplate = async (template) => {
    try {
      const result = await ingestionApi.downloadTemplate(template.id);
      if (!result.url) return;
      const link = document.createElement("a");
      link.href = result.url;
      link.download = result.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      globalThis.setTimeout(() => URL.revokeObjectURL(result.url), 1000);
      setDownloadedTemplates((current) =>
        current.includes(template.id) ? current : [...current, template.id]
      );
    } catch (error) {
      console.error("Download failed:", error);
      setNotice({
        variant: "error",
        message: dataConnectionErrorMessage(error, t)
      });
    }
  };

  const downloadProductReference = async () => {
    try {
      const result = await ingestionApi.downloadProductReference();
      const link = document.createElement("a");
      link.href = result.url;
      link.download = result.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      globalThis.setTimeout(() => URL.revokeObjectURL(result.url), 1000);
    } catch (error) {
      setNotice({ variant: "error", message: dataConnectionErrorMessage(error, t) });
    }
  };

  const showStructuredError = (error) => {
    const apiError = getApiError(error);
    const issue = apiError.details?.issues?.[0];
    const description = issue
      ? `${importSheetLabel(issue.sheet, t)}, ${t("connectData.feedback.rowNumber", { row: issue.row })}: ${formatImportIssue(issue.message, t, { fallback: t('connectData.review.issues.generic') })}`
      : apiError.details?.message ? formatImportIssue(apiError.details.message, t, { fallback: t('connectData.review.issues.generic') }) : dataConnectionErrorMessage(error, t);
    setNotice({ variant: "error", message: description });
  };

  const previewImport = async () => {
    if (files.length !== 1) {
      setNotice({ variant: "error", message: t("connectData.review.oneFile") });
      return;
    }
    setImportBusy(true);
    try {
      const preview = await ingestionApi.previewBusinessImport(files[0], importKind);
      if (!preview?.draftId || preview.kind !== importKind) throw new Error(t("connectData.review.previewFailed"));
      setImportPreview(preview);
      setProductChoices({});
      setImportReview(null);
      setNotice(null);
    } catch (error) { showStructuredError(error); }
    finally { setImportBusy(false); }
  };

  const setProductChoice = (match, choice) => {
    const similar = importPreview.matches.filter((entry) => entry.status === match.status &&
      entry.productName.trim().toLocaleLowerCase() === match.productName.trim().toLocaleLowerCase() &&
      entry.sku.trim().toLocaleLowerCase() === match.sku.trim().toLocaleLowerCase());
    setProductChoices((current) => {
      const next = { ...current };
      for (const entry of similar) {
        if (choice) next[entry.key] = choice;
        else delete next[entry.key];
      }
      return next;
    });
    setImportReview(null);
  };

  const reviewImport = async () => {
    setImportBusy(true);
    try {
      const result = await ingestionApi.reviewBusinessImport(importKind, importPreview.draftId, productChoices);
      if (!result?.reviewHash) throw new Error(t("connectData.review.previewFailed"));
      setImportReview(result);
      setNotice(null);
    } catch (error) { setImportReview(null); showStructuredError(error); }
    finally { setImportBusy(false); }
  };

  const confirmImport = async () => {
    if (!importReview) return;
    setImportBusy(true);
    try {
      const result = await ingestionApi.confirmBusinessImport(importKind, importPreview.draftId, productChoices, importReview.reviewHash);
      setNotice({ variant: "success", message: t("connectData.review.imported", {
        invoices: result.kind === "invoices" ? result.imported : 0,
        items: result.invoiceItems,
        inventory: result.kind === "inventory" ? result.imported + result.updated : 0
      }) });
      setFiles([]);
      setImportPreview(null);
      setImportReview(null);
      setProductChoices({});
      await query.refetch();
      await queryClient.invalidateQueries({ queryKey: ["dashboard-aggregate", companyId] });
    } catch (error) { setImportReview(null); showStructuredError(error); }
    finally { setImportBusy(false); }
  };

  const prepareImport = async () => {
    if (importBusy || files.length === 0) return;
    if (importKind !== "sales") return previewImport();
    setImportBusy(true);
    try {
      const result = await ingestionApi.prepareFiles(files, importKind);
      const recoveredRows = result.files.reduce((sum, item) =>
        sum + (item.extractionData?.recovered ? item.extractionData.added_row_count ?? 0 : 0), 0);
      const receivedRows = result.files.reduce((sum, item) =>
        sum + (item.status === "success" ? item.extractionData?.staged_row_count ?? 0 : 0), 0);
      const salesReceipt = receivedRows > 0 ? " " + t("connectData.feedback.salesRowsReceived", { count: receivedRows }) : "";
      const recoveryReceipt = recoveredRows > 0 ? " " + t("connectData.feedback.salesRowsRecovered", { count: recoveredRows }) : "";
      const failedFiles = result.files.filter((item) => item.status === "failed");
      if (failedFiles.length) {
        setFiles(failedFiles.map((item) => files[item.index]));
        const firstFailure = failedFiles[0];
        const apiError = getApiError(firstFailure.error);
        const details = apiError.details;
        const firstIssue = details && typeof details === "object" ? details.issues?.[0] : null;
        const reason = firstIssue
          ? `${importSheetLabel(firstIssue.sheet, t)}, ${t("connectData.feedback.rowNumber", { row: firstIssue.row })}: ${formatImportIssue(firstIssue.message, t, { fallback: t('connectData.review.issues.generic') })}`
          : formatImportIssue(typeof details === 'string' ? details : details?.message, t, { fallback: '' }) || dataConnectionErrorMessage(firstFailure.error, t);
        const errorCode = apiError.code ? ` [${apiError.code}]` : "";
        setNotice({
          variant: "error",
          message: t(importKind === "sales" ? "connectData.feedback.partialUpload" : "connectData.feedback.structuredPartial", {
            succeeded: result.succeeded,
            duplicates: result.duplicates,
            failed: result.failed
          }) + salesReceipt + recoveryReceipt + ` ${firstFailure.name}: ${reason}${errorCode}`
        });
      } else if (result.succeeded === 0 && result.duplicates > 0) {
        setNotice({
          variant: "success",
          message: t("connectData.feedback.duplicateUpload", {
            count: result.duplicates
          })
        });
        setFiles([]);
      } else {
        setNotice({
          variant: "success",
          message: importKind === "sales"
            ? t("connectData.feedback.uploaded", { count: result.succeeded, duplicates: result.duplicates }) + salesReceipt + recoveryReceipt
            : t("connectData.feedback.structuredImported", {
                count: result.files.reduce((sum, item) => sum + (item.imported || 0) + (item.updated || 0), 0)
              })
        });
        setFiles([]);
      }
      await query.refetch();
    } catch (error) {
      console.error("Upload failed:", error);

      // Extract the exact error message from your backend validator (e.g., "Missing required columns")
      const backendMessage = dataConnectionErrorMessage(error, t);

      setNotice({
        variant: "error",
        message:
          backendMessage ||
          t("connectData.feedback.uploadFailed")
      });
    } finally {
      setImportBusy(false);
    }
  };

  if (query.isPending)
    return (
      <div className="connect-data-loading" aria-busy="true">
        <Skeleton height="76px" variant="rectangular" />
        <div>
          {Array.from({ length: 3 }, (_, index) => (
            <Skeleton key={index} height="220px" variant="rectangular" />
          ))}
        </div>
        <Skeleton height="300px" variant="rectangular" />
      </div>
    );

  if (query.isError)
    return (
      <EmptyState
        title={t("connectData.error.title")}
        description={dataConnectionErrorMessage(query.error, t)}
        action={
          <Button size="sm" variant="outline" onClick={() => query.refetch()}>
            {t("connectData.actions.retry")}
          </Button>
        }
      />
    );

  const data = query.data;

  return (
    <div className="connect-data-page" dir={dir}>
      <PageHeader
        title={t("connectData.page.title")}
        subtitle={t("connectData.page.subtitle")}
        actions={
          <Button
            size="sm"
            leadingIcon={<Plus size={15} />}
            onClick={() => setAddOpen(true)}
          >
            {t("connectData.actions.addSource")}
          </Button>
        }
      />
      <p className="connect-data-supporting">
        {t("connectData.page.supporting")}
      </p>

      <section className="connect-data-section">
        <div className="connect-data-section__header">
          <div>
            <h2>{t("connectData.connected.title")}</h2>
            <p>{t("connectData.connected.subtitle")}</p>
          </div>
          <span>
            {t("connectData.connected.count", {
            count: number.format(data.sourceCapacity?.currentUsage ?? 0),
            limit: data.sourceCapacity?.isUnlimited
              ? t("connectData.connected.unlimited")
              : number.format(data.sourceCapacity?.limit ?? 0)
            })}
            {!data.sourceCapacity?.isUnlimited && !data.sourceCapacity?.isOverLimit && (
              <small className="connect-data-capacity-remaining">
                {t("connectData.connected.remaining", {
                  count: number.format(data.sourceCapacity?.remaining ?? 0)
                })}
              </small>
            )}
            {data.sourceCapacity?.included !== false && data.sourceCapacity?.isOverLimit && (
              <small className="connect-data-capacity-warning" role="status">
                {t("connectData.connected.overLimit", {
                  count: number.format(data.sourceCapacity.currentUsage),
                  limit: number.format(data.sourceCapacity.limit ?? 0)
                })}
              </small>
            )}
            {data.sourceCapacity?.included === false && (
              <small className="connect-data-capacity-warning" role="status">
                {t("connectData.connected.integrationUnavailable")}
              </small>
            )}
          </span>
        </div>

        {data.connectedSources?.length ? (
          <div className="connected-source-grid">
            {data.connectedSources.map((source) => (
              <ConnectedSourceCard
                key={source.id}
                source={source}
                t={t}
                localize={localize}
                locale={locale}
                formatDate={formatDate}
                formatNumber={number.format}
                onAction={runSourceAction}
                busy={busySource === source.id}
              />
            ))}
          </div>
        ) : (
          <EmptyState
            title={t("connectData.empty.title")}
            description={t("connectData.empty.description")}
            action={
              <Button size="sm" onClick={() => setAddOpen(true)}>
                {t("connectData.actions.addSource")}
              </Button>
            }
          />
        )}
      </section>

      <section
        ref={uploadRef}
        className="connect-data-section connect-data-upload"
      >
        <div className="connect-data-section__header">
          <div>
            <h2>{t("connectData.upload.title")}</h2>
            <p>{t("connectData.upload.subtitle")}</p>
          </div>
        </div>
        <div className="connect-data-upload__kind">
          <label htmlFor="business-import-kind">{t("connectData.upload.importKind")}</label>
          <select
            id="business-import-kind"
            value={importKind}
            disabled={importBusy}
            onChange={(event) => {
              setImportKind(event.target.value);
              setFiles([]);
              setImportPreview(null);
              setImportReview(null);
              setProductChoices({});
            }}
          >
            {['sales', 'invoices', 'inventory'].map((kind) => (
              <option key={kind} value={kind}>{t(`connectData.upload.kinds.${kind}`)}</option>
            ))}
          </select>
          <p>{t(`connectData.upload.help.${importKind}`)}</p>
        </div>
        <div className="connect-data-upload__grid">
          <div>
            <h3>{t("connectData.upload.templates")}</h3>
            <div className="ceopro-template-options">
              {getDataTemplateOptions(importKind).map((template) => (
                <button
                  className="ceopro-template-option"
                  type="button"
                  key={template.id}
                  onClick={() => downloadTemplate(template)}
                >
                  <img src={template.icon} alt="" />
                  <strong>{t(template.labelKey)}</strong>
                  <span>
                    {downloadedTemplates.includes(template.id) ? (
                      <Check size={14} />
                    ) : (
                      <Download size={14} />
                    )}
                    {t(
                      downloadedTemplates.includes(template.id)
                        ? "dataIngestion.templates.downloaded"
                        : "dataIngestion.templates.download"
                    )}
                  </span>
                </button>
              ))}
            </div>
            {importKind !== "sales" && (
              <Button size="sm" variant="outline" className="connect-data-product-reference" leadingIcon={<Download size={14} />} onClick={downloadProductReference}>
                {t("connectData.upload.productReference")}
              </Button>
            )}
          </div>
          <div>
            <h3>{t("connectData.upload.files")}</h3>
            <FeatureGate
              featureCode="document_extraction"
              mode={importKind === "sales" ? "access" : "consume"}
              compact
            >
              <div>
                <FileUploadDropzone key={importKind} kind={importKind} files={files} disabled={importBusy} onFilesChange={(next) => {
                  setFiles(next); setImportPreview(null); setImportReview(null); setProductChoices({});
                }} />
                {files.length > 0 && !importPreview && (
                  <Button
                    className="connect-data-prepare"
                    size="sm"
                    loading={importBusy}
                    loadingLabel={t(importKind === "sales" ? "connectData.actions.importing" : "connectData.review.preparing")}
                    onClick={prepareImport}
                  >
                    {t(importKind === "sales" ? "connectData.actions.prepareImport" : "connectData.review.previewButton")}
                  </Button>
                )}
              </div>
            </FeatureGate>
          </div>
        </div>
        {importPreview && <StructuredImportReview preview={importPreview} choices={productChoices} review={importReview}
          busy={importBusy} onChoice={setProductChoice} onReview={reviewImport} onConfirm={confirmImport}
          onCancel={() => { setImportPreview(null); setImportReview(null); setProductChoices({}); }} locale={locale} t={t} />}
      </section>

      <section className="connect-data-section">
        <div className="connect-data-section__header">
          <div>
            <h2>{t("connectData.activity.title")}</h2>
            <p>{t("connectData.activity.subtitle")}</p>
          </div>
        </div>
        {data.recentImports?.length ? (
          <div className="connect-data-table-wrap">
            <table className="connect-data-table">
              <thead>
                <tr>
                  <th>{t("connectData.activity.date")}</th>
                  <th>{t("connectData.activity.source")}</th>
                  <th>{t("connectData.activity.name")}</th>
                  <th>{t("connectData.activity.type")}</th>
                  <th>{t("connectData.activity.status")}</th>
                  <th>{t("connectData.activity.details")}</th>
                </tr>
              </thead>
              <tbody>
                {data.recentImports.map((item) => (
                  <tr key={item.id}>
                    <td>{formatDate(item.date)}</td>
                    <td>{localize(item.source)}</td>
                    <td>{activityName(item, locale, t)}</td>
                    <td>
                      {activityTypeLabel(item.type, t)}
                    </td>
                    <td>
                      <ConnectionStatusBadge status={item.status} t={t} />
                    </td>
                    <td>
                      <Button size="sm" variant="outline" disabled={jobBusy} onClick={() => openJobDetails(item.id)}>
                        {t("connectData.actions.details")}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            title={t("connectData.activity.emptyTitle")}
            description={t("connectData.activity.emptyDescription")}
          />
        )}
      </section>

      <Modal
        isOpen={addOpen}
        onClose={() => setAddOpen(false)}
        title={t("connectData.add.title")}
        closeLabel={t("common.close")}
        maxWidth="900px"
      >
        <p className="connect-data-modal-copy">
          {t("connectData.add.subtitle")}
        </p>
        <div className="ceopro-data-source-grid connect-data-source-selector">
          <FeatureGate featureCode="data_integration" mode="access" compact>
            <FeatureGate
              featureCode="connected_data_sources"
              mode="consume"
              compact
            >
              {(data.availableSourceTypes || [])
                .filter((type) => type !== "documents")
                .map(renderSourceOption)}
            </FeatureGate>
          </FeatureGate>
          {(data.availableSourceTypes || []).includes("documents") &&
            renderSourceOption("documents")}
        </div>
      </Modal>

      <WebsiteStoreSetup isOpen={storeSetupOpen} initialUrl={websiteUrl} sourceId={storeSourceId} t={t} onClose={()=>setStoreSetupOpen(false)} onConnected={async result=>{setWebsiteUrl("");setNotice({variant:"success",message:t(result.connectionStatus==="connected"?"storeConnection.syncQueued":"connectData.feedback.sourceConfigured")});await query.refetch();}}/>
      <Modal
        isOpen={Boolean(detailSource)}
        onClose={() => setDetailSource(null)}
        title={detailSource ? localize(detailSource.name) : ""}
        closeLabel={t("common.close")}
        maxWidth="560px"
      >
        {detailSource && (
          <div className="connect-data-details">
            <ConnectionStatusBadge status={detailSource.status} t={t} />
            {detailSource.provider==='shopify'&&<p>{t(detailSource.historyAccess==='recent'?'storeConnection.shopify.history':'storeConnection.shopify.allHistory')}</p>}
            {detailSource.provider==='shopify'&&detailSource.actions?.includes('connectStore')&&<ShopifyPrivacyReports sourceId={detailSource.id} t={t}/>}
            {detailSource.storeError && <p role="alert">{storeErrorMessage({ code: detailSource.storeError }, t)}</p>}
            <dl>
              <div>
                <dt>{t("connectData.connected.updatedLabel")}</dt>
                <dd>{formatDate(detailSource.lastUpdatedAt)}</dd>
              </div>
              {detailSource.lastAttemptAt && (
                <div>
                  <dt>{t("connectData.connected.lastAttempt")}</dt>
                  <dd>{formatDate(detailSource.lastAttemptAt)}</dd>
                </div>
              )}
              {detailSource.sourceUrl && (
                <div>
                  <dt>{t("connectData.connected.sourceUrl")}</dt>
                  <dd><a href={detailSource.sourceUrl} target="_blank" rel="noreferrer">{detailSource.sourceUrl}</a></dd>
                </div>
              )}
              <div>
                <dt>{t("connectData.connected.verification")}</dt>
                <dd>
                  {t(
                    detailSource.status === "synced"
                      ? "connectData.connected.syncVerified"
                      : detailSource.status === "disconnected"
                        ? "connectData.connected.disconnectedHelp"
                      : detailSource.status === "needsAttention"
                        ? detailSource.latestJobStatus === "completed"
                          ? "connectData.connected.syncNotPromoted"
                          : "connectData.statuses.failedHelp"
                        : "connectData.connected.configuredHelp"
                  )}
                </dd>
              </div>
              {detailSource.recordCount != null && (
                <div>
                  <dt>{t("connectData.connected.records")}</dt>
                  <dd>{number.format(detailSource.recordCount)}</dd>
                </div>
              )}
              <div>
                <dt>{t("connectData.connected.categories")}</dt>
                <dd>{detailSource.categories.map(value => dataCategoryLabel(value, locale, t)).join(" · ")}</dd>
              </div>
            </dl>
          </div>
        )}
      </Modal>

      <Modal
        isOpen={Boolean(disconnectSource)}
        onClose={() => setDisconnectSource(null)}
        title={t("connectData.disconnect.title")}
        closeLabel={t("common.close")}
        maxWidth="520px"
      >
        {disconnectSource && (
          <div className="connect-data-disconnect-confirmation">
            <p>{t("connectData.disconnect.description", {
              name: localize(disconnectSource.name)
            })}</p>
            <Button
              variant="secondary"
              loading={busySource === disconnectSource.id}
              onClick={confirmDisconnect}
            >
              {t("connectData.actions.disconnect")}
            </Button>
          </div>
        )}
      </Modal>

      <Modal
        isOpen={Boolean(detailJob)}
        onClose={() => {
          setDetailJob(null);
          setDetailJobRows([]);
        }}
        title={t("connectData.job.title")}
        closeLabel={t("common.close")}
        maxWidth="900px"
      >
        {detailJob && (
          <div className="connect-data-job-details">
            <IngestionJobStatusTable
              job={detailJob}
              t={t}
              formatDate={formatDate}
            />
            {detailJob.retryable && (
              <Button size="sm" loading={jobBusy} onClick={retrySelectedJob}>
                {t("connectData.actions.retry")}
              </Button>
            )}
            <h3>{t("connectData.job.stagingTitle")}</h3>
            <StagingRowReviewGrid
              rows={detailJobRows}
              t={t}
              onSave={saveStagingCorrection}
            />
            {detailJobTotal > 50 && (
              <div className="connect-data-job-pagination">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={jobBusy || detailJobPage <= 1}
                  onClick={() => loadJobStagingPage(detailJobPage - 1)}
                >
                  {t("common.previous")}
                </Button>
                <span>
                  {detailJobPage} / {Math.ceil(detailJobTotal / 50)}
                </span>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={jobBusy || detailJobPage >= Math.ceil(detailJobTotal / 50)}
                  onClick={() => loadJobStagingPage(detailJobPage + 1)}
                >
                  {t("common.next")}
                </Button>
              </div>
            )}
          </div>
        )}
      </Modal>

      {notice && (
        <div className="connect-data-toast">
          <Toast
            variant={notice.variant}
            message={notice.message}
            onClose={() => setNotice(null)}
          />
        </div>
      )}
    </div>
  );
}
