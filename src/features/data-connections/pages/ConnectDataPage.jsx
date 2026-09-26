import { useMemo, useRef, useState } from "react";
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
import { DATA_TEMPLATE_OPTIONS } from "../../data-ingestion/config/dataTemplateOptions.js";
import { ingestionApi } from "../../data-ingestion/api/ingestionApi.js";
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

  const [addOpen, setAddOpen] = useState(false);
  const [detailSource, setDetailSource] = useState(null);
  const [files, setFiles] = useState([]);
  const [downloadedTemplates, setDownloadedTemplates] = useState([]);
  const [websiteUrl, setWebsiteUrl] = useState("");
  const [busySource, setBusySource] = useState(null);
  const [notice, setNotice] = useState(null);
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

  const localize = (value) =>
    value && typeof value === "object" ? value[locale] || value.en : value;
  const formatDate = (value) => date.format(new Date(value));

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

  const runSourceAction = async (action, source) => {
    if (action === "details") return setDetailSource(source);
    if (action === "uploadVersion") return goToUpload();

    setBusySource(source.id);
    try {
      if (action === "reconnect") {
        await dataConnectionsApi.reconnect(source.id);
        setNotice({
          variant: "success",
          message: t(
            "connectData.feedback.reconnected",
            "Reconnected successfully"
          )
        });
      } else {
        await dataConnectionsApi.sync(source.id);
        setNotice({
          variant: "success",
          message: t("connectData.feedback.syncStarted", "Data sync started")
        });
      }
      query.refetch(); // Refresh the UI to reflect new job status
    } catch (error) {
      console.error("Action failed:", error);
      setNotice({
        variant: "error",
        message: t(
          "connectData.feedback.actionFailed",
          "Action failed. Please try again."
        )
      });
    } finally {
      setBusySource(null);
    }
  };

  const connectSource = async (type) => {
    if (type === "documents") return goToUpload();
    if (type === "website" && !websiteUrl.trim()) return;

    setBusySource(type);
    try {
      if (type === "analytics") {
        await dataConnectionsApi.connectGoogleAnalytics({ companyId });
      } else if (type === "website") {
        await dataConnectionsApi.configureWebsite({
          companyId,
          url: websiteUrl.trim()
        });
      } else {
        await dataConnectionsApi.prepareDatabase({ companyId });
      }

      setNotice({
        variant: "success",
        message: t(
          "connectData.feedback.sourceConnected",
          "Data source connected successfully"
        )
      });
      setAddOpen(false);
      setWebsiteUrl(""); // Clear input on success
      query.refetch(); // Refresh UI with new connection
    } catch (error) {
      console.error("Connection failed:", error);
      setNotice({
        variant: "error",
        message: t(
          "connectData.feedback.connectionFailed",
          "Failed to connect data source."
        )
      });
    } finally {
      setBusySource(null);
    }
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
      setDownloadedTemplates((current) =>
        current.includes(template.id) ? current : [...current, template.id]
      );
    } catch (error) {
      console.error("Download failed:", error);
      setNotice({
        variant: "error",
        message: t(
          "connectData.feedback.downloadFailed",
          "Failed to download template."
        )
      });
    }
  };

  const prepareImport = async () => {
    try {
      await ingestionApi.prepareFiles(files);

      setNotice({
        variant: "success",
        message: t(
          "connectData.feedback.uploaded",
          "Files uploaded and processing started."
        )
      });
      setFiles([]); // Clear dropzone on success
      query.refetch(); // Refresh activity table
    } catch (error) {
      console.error("Upload failed:", error);

      // Extract the exact error message from your backend validator (e.g., "Missing required columns")
      const backendMessage = error.response?.data?.error?.message;

      setNotice({
        variant: "error",
        message:
          backendMessage ||
          t(
            "connectData.feedback.uploadFailed",
            "Failed to upload files. Please check requirements."
          )
      });
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
        description={t("connectData.error.description")}
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
              count: number.format(data.connectedSources?.length || 0)
            })}
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
        <div className="connect-data-upload__grid">
          <div>
            <h3>{t("connectData.upload.templates")}</h3>
            <div className="ceopro-template-options">
              {DATA_TEMPLATE_OPTIONS.map((template) => (
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
          </div>
          <div>
            <h3>{t("connectData.upload.files")}</h3>
            <FeatureGate
              featureCode="document_extraction"
              mode="consume"
              compact
            >
              <div>
                <FileUploadDropzone files={files} onFilesChange={setFiles} />
                {files.length > 0 && (
                  <Button
                    className="connect-data-prepare"
                    size="sm"
                    onClick={prepareImport}
                  >
                    {t("connectData.actions.prepareImport")}
                  </Button>
                )}
              </div>
            </FeatureGate>
          </div>
        </div>
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
                </tr>
              </thead>
              <tbody>
                {data.recentImports.map((item) => (
                  <tr key={item.id}>
                    <td>{formatDate(item.date)}</td>
                    <td>{localize(item.source)}</td>
                    <td>{localize(item.name)}</td>
                    <td>
                      {t(
                        `connectData.fileTypes.${item.type?.toLowerCase()}`,
                        item.type
                      )}
                    </td>
                    <td>
                      <ConnectionStatusBadge status={item.status} t={t} />
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
        <FeatureGate
          featureCode="connected_data_sources"
          mode="consume"
          compact
        >
          <div className="ceopro-data-source-grid connect-data-source-selector">
            {(data.availableSourceTypes || []).map((type) => (
              <DataSourceCard
                key={type}
                icon={sourceIcons[type]}
                title={t(`dataConnections.${type}.title`)}
                description={t(`dataConnections.${type}.description`)}
                actionLabel={t(`dataConnections.${type}.action`)}
                showStatus={false}
                loading={busySource === type}
                actionDisabled={type === "website" && !websiteUrl.trim()}
                onAction={() => connectSource(type)}
              >
                {type === "website" && (
                  <input
                    className="ceopro-setup-url-input"
                    type="url"
                    value={websiteUrl}
                    onChange={(event) => setWebsiteUrl(event.target.value)}
                    placeholder="https://your-website.com"
                    aria-label={t("dataConnections.website.inputLabel")}
                  />
                )}
              </DataSourceCard>
            ))}
          </div>
        </FeatureGate>
      </Modal>

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
            <dl>
              <div>
                <dt>{t("connectData.connected.updatedLabel")}</dt>
                <dd>{formatDate(detailSource.lastUpdatedAt)}</dd>
              </div>
              {detailSource.recordCount != null && (
                <div>
                  <dt>{t("connectData.connected.records")}</dt>
                  <dd>{number.format(detailSource.recordCount)}</dd>
                </div>
              )}
              <div>
                <dt>{t("connectData.connected.categories")}</dt>
                <dd>{detailSource.categories.map(localize).join(" · ")}</dd>
              </div>
            </dl>
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
