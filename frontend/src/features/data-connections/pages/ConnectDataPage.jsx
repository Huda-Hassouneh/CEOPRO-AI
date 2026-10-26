import {StructuredBusinessImport} from '../../data-ingestion/components/StructuredBusinessImport.jsx';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Check, Database, Download, FileText, Plug, Plus, RefreshCw, ShoppingBag, Store, Unplug } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import PageHeader from '../../../shared/components/layout/PageHeader.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import Modal from '../../../shared/components/ui/Modal.jsx';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import Toast from '../../../shared/components/ui/Toast.jsx';
import { FileUploadDropzone } from '../../data-ingestion/components/FileUploadDropzone.jsx';
import { DATA_TEMPLATE_OPTIONS } from '../../data-ingestion/config/dataTemplateOptions.js';
import { ingestionApi } from '../../data-ingestion/api/ingestionApi.js';
import { retainFailedImportFiles, summarizeImport } from '../../data-ingestion/utils/importSummary.js';
import { ImportDraftsPanel } from '../../data-ingestion/components/ImportDraftsPanel.jsx';
import { ProviderRecordsPanel } from '../components/ProviderRecordsPanel.jsx';
import { ConnectSystemForm } from '../components/ConnectSystemForm.jsx';
import { ConnectStoreForm } from '../components/ConnectStoreForm.jsx';
import { ApexButton, Pill } from '../../../shared/components/apex/Apex.jsx';
import { ConnectionStatusBadge } from '../components/ConnectionStatusBadge.jsx';
import { CustomerReviewsSection } from '../components/CustomerReviewsSection.jsx';
import { dataConnectionsApi } from '../api/dataConnectionsApi.js';
import { useDataConnections } from '../hooks/useDataConnections.js';
import '../styles/DataConnections.css';
import '../../data-ingestion/styles/DataIngestion.css';
import '../styles/ConnectDataPage.css';
import '../../onboarding/styles/Setup.css';

const ADD_OPTIONS = [
  { kind: 'documents', icon: FileText },
  { kind: 'api', icon: Plug },
  { kind: 'database', icon: Database },
  { kind: 'woocommerce', icon: ShoppingBag },
  { kind: 'shopify', icon: Store },
];

export function ConnectDataPage() {
  const { t, locale, dir } = useI18n();
  const queryClient = useQueryClient();
  const [syncWatch, setSyncWatch] = useState(null);
  const query = useDataConnections({ pollWhileSyncQueued: Boolean(syncWatch) });
  const [addOpen, setAddOpen] = useState(false);
  const [connectKind, setConnectKind] = useState(null);
  const [files, setFiles] = useState([]);
  const [downloadedTemplates, setDownloadedTemplates] = useState([]);
  const [busySource, setBusySource] = useState(null);
  const [providerRecordsSource, setProviderRecordsSource] = useState(null);
  const [importing, setImporting] = useState(false);
  const [notice, setNotice] = useState(null);
  const shopifyFinishStarted = useRef(false);
  const uploadRef = useRef(null);
  const number = useMemo(() => new Intl.NumberFormat(locale), [locale]);
  const date = useMemo(() => new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }), [locale]);
  const localize = (value) => value && typeof value === 'object' ? value[locale] || value.en : value;
  const formatDate = (value) => date.format(new Date(value));

  useEffect(() => {
    if (!syncWatch) return undefined;
    const current = query.data?.connectedSources?.find((source) => source.source_id === syncWatch.sourceId);
    const run = current?.last_run;
    if (run?.job_id && run.job_id !== syncWatch.previousJobId && ['COMPLETED', 'FAILED'].includes(run.status)) {
      setSyncWatch(null);
    }
  }, [query.data, syncWatch]);

  useEffect(() => {
    if (!syncWatch) return undefined;
    const timeout = globalThis.setTimeout(() => setSyncWatch(null), 120000);
    return () => globalThis.clearTimeout(timeout);
  }, [syncWatch]);

  useEffect(() => {
    const query = new URLSearchParams(globalThis.location.search);
    if (query.get('shopify') === 'error') {
      globalThis.history.replaceState(null, '', globalThis.location.pathname);
      setNotice({ variant: 'error', message: t('connectData.store.callbackFailed') });
      return;
    }
    const callback = new URLSearchParams(globalThis.location.hash.slice(1));
    const ticket = callback.get('shopify_ticket');
    if (!ticket) return;
    const state = callback.get('shopify_state');
    // Remove the short-lived ticket from browser history before sending it to
    // the authenticated finish endpoint.
    globalThis.history.replaceState(null, '', `${globalThis.location.pathname}${globalThis.location.search}`);
    if (!state || shopifyFinishStarted.current) {
      setNotice({ variant: 'error', message: t('connectData.store.finishFailed') });
      return;
    }
    shopifyFinishStarted.current = true;
    dataConnectionsApi.completeShopifyConnect(ticket).then(() => {
      queryClient.invalidateQueries({ queryKey: ['data-connections'] });
      setNotice({ variant: 'success', message: t('connectData.store.connected') });
    }).catch((error) => {
      const status = error?.response?.status;
      setNotice({ variant: 'error', message: status === 401 ? t('connectData.store.sessionExpired')
        : status === 403 ? t('connectData.system.adminOnly')
          : status === 409 ? t('connectData.store.conflict') : t('connectData.store.finishFailed') });
    });
  }, [queryClient, t]);

  const goToUpload = () => {
    setAddOpen(false);
    globalThis.setTimeout(() => uploadRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 0);
  };
  const statusLabel = (status) => { const key = `connectData.system.status.${status}`; const label = t(key); return label === key ? status : label; };
  const chooseOption = (kind) => (kind === 'documents' ? goToUpload() : setConnectKind(kind));
  const closeAdd = () => { setAddOpen(false); setConnectKind(null); };
  const connected = () => {
    closeAdd();
    queryClient.invalidateQueries({ queryKey: ['data-connections'] });
    setNotice({ variant: 'success', message: t('connectData.system.connected') });
  };
  const runSourceAction = async (action, source) => {
    setBusySource(source.source_id);
    try {
      if (action === 'sync') {
        setSyncWatch({ sourceId: source.source_id, previousJobId: source.last_run?.job_id ?? null });
        await dataConnectionsApi.syncNow(source.source_id);
        setNotice({ variant: 'success', message: t('connectData.system.syncQueued') });
      } else {
        await dataConnectionsApi.disconnect(source.source_id);
        setNotice({ variant: 'success', message: t('connectData.system.disconnected') });
      }
      queryClient.invalidateQueries({ queryKey: ['data-connections'] });
    } catch (error) {
      if (action === 'sync') setSyncWatch(null);
      setNotice({ variant: 'error', message: t(error?.response?.status === 403 ? 'connectData.system.adminOnly' : 'connectData.system.actionFailed') });
    } finally {
      setBusySource(null);
    }
  };
  const downloadTemplate = async (template) => {
    const result = await ingestionApi.downloadTemplate(template.id);
    if (!result.url) return;
    const link = document.createElement('a');
    link.href = result.url;
    link.download = result.filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setDownloadedTemplates((current) => current.includes(template.id) ? current : [...current, template.id]);
  };
  const prepareImport = async () => {
    // Real bug found live in first-customer E2E testing: /extraction/upload
    // fully commits server-side (products/invoices/invoice_items) with no
    // idempotency guard, and this button had no pending/disabled state -
    // a real user re-clicking it (nothing visibly happens until the
    // response returns, and a 73-row import takes a few seconds) fires a
    // second full import of the same file, silently doubling their sales
    // data with no error or warning. Guarding the click itself is the
    // direct fix for that trigger.
    if (importing) return;
    setImporting(true);
    try {
      const result = await ingestionApi.prepareFiles(files);
      if (result.uploaded) {
        // Every other mutation that changes products (useCreateProduct/
        // useUpdateProduct/useDeleteProduct/useQuickSale) already invalidates
        // this same key on success - a real upload creates products via the
        // extraction pipeline too, so the Products page's cached list has to
        // be invalidated the same way, or it keeps showing whatever it had
        // cached (including "No products yet" for an account with none yet)
        // until an unrelated full page reload happens to refetch it.
        queryClient.invalidateQueries({ queryKey: ['products'] });
      }
      // Failed files are recorded too, so refresh the import history either way.
      queryClient.invalidateQueries({ queryKey: ['data-connections'] });
      queryClient.invalidateQueries({ queryKey: ['import-drafts'] });
      setNotice(summarizeImport(result.files, t, number.format));
      setFiles((selected) => retainFailedImportFiles(selected, result.files));
    } finally {
      setImporting(false);
    }
  };

  if (query.isPending) return <div className="connect-data-loading" aria-busy="true"><Skeleton height="76px" variant="rectangular" /><div>{Array.from({ length: 3 }, (_, index) => <Skeleton key={index} height="220px" variant="rectangular" />)}</div><Skeleton height="300px" variant="rectangular" /></div>;
  if (query.isError) return <EmptyState title={t('connectData.error.title')} description={t('connectData.error.description')} action={<Button size="sm" variant="outline" onClick={() => query.refetch()}>{t('connectData.actions.retry')}</Button>} />;
  const data = query.data;
  const providerSource = data.connectedSources.find((source) => source.source_id === providerRecordsSource);

  return <div className="connect-data-page" dir={dir}>
    <PageHeader title={t('connectData.page.title')} subtitle={t('connectData.page.subtitle')} actions={<Button size="sm" leadingIcon={<Plus size={15} />} onClick={() => setAddOpen(true)}>{t('connectData.actions.addSource')}</Button>} />
    <p className="connect-data-supporting">{t('connectData.page.supporting')}</p>

    <section className="connect-data-section">
      <div className="connect-data-section__header"><div><h2>{t('connectData.connected.title')}</h2><p>{t('connectData.connected.subtitle')}</p></div><span>{t('connectData.connected.count', { count: number.format(data.connectedSources.length) })}</span></div>
      {data.connectedSources.length ? (
        <ul className="connected-systems">
          {data.connectedSources.map((source) => (
            <li key={source.source_id}>
              <span className="connected-systems__icon" aria-hidden="true">{source.kind === 'database' ? <Database size={18} /> : source.kind === 'woocommerce' ? <ShoppingBag size={18} /> : source.kind === 'shopify' ? <Store size={18} /> : <Plug size={18} />}</span>
              <div>
                <strong>{source.name}</strong>
                <span className="apex-muted">{t(source.kind === 'woocommerce' || source.kind === 'shopify' ? `connectData.store.${source.kind}` : `connectData.system.kind.${source.kind}`)} · {t(`connectData.system.every.${[15, 60, 360, 1440].includes(source.sync_frequency_minutes) ? source.sync_frequency_minutes : 1440}`)}</span>
                {(source.kind === 'woocommerce' || source.kind === 'shopify') && <span className="apex-muted">{t(`connectData.store.status.${source.connection_status || 'active'}`)}{source.verified_at ? ` · ${t('connectData.store.verifiedAt', { date: formatDate(source.verified_at) })}` : ''}</span>}
                <span className="apex-muted">{source.last_synced_at ? t('connectData.system.lastSynced', { date: formatDate(source.last_synced_at) }) : t('connectData.system.notSyncedYet')}
                  {source.last_run && ` · ${t('connectData.system.lastRun', { rows: number.format(source.last_run.rows_processed || 0) })}`}</span>
              </div>
              {(source.last_run?.status || syncWatch?.sourceId === source.source_id) && <Pill tone={source.last_run?.status === 'COMPLETED' ? 'success' : source.last_run?.status === 'FAILED' ? 'danger' : 'neutral'}>{syncWatch?.sourceId === source.source_id && (!source.last_run?.job_id || source.last_run.job_id === syncWatch.previousJobId) ? t('connectData.store.status.QUEUED') : statusLabel(source.last_run?.status || 'QUEUED')}</Pill>}
              <div className="connected-systems__actions">
                {['shopify', 'woocommerce'].includes(source.kind) && <ApexButton size="sm" variant="ghost" icon={Store}
                  onClick={() => setProviderRecordsSource((current) => current === source.source_id ? null : source.source_id)}>
                  {providerRecordsSource === source.source_id ? t('connectData.providerRecords.close') : t('connectData.providerRecords.open')}
                </ApexButton>}
                {['shopify', 'woocommerce'].includes(source.kind) && source.connection_status !== 'verified'
                  ? <ApexButton size="sm" variant="secondary" icon={source.kind === 'shopify' ? Store : ShoppingBag} onClick={() => { setConnectKind(source.kind); setAddOpen(true); }}>{t('connectData.store.reconnect')}</ApexButton>
                  : <ApexButton size="sm" variant="secondary" icon={RefreshCw} loading={busySource === source.source_id} disabled={syncWatch?.sourceId === source.source_id} onClick={() => runSourceAction('sync', source)}>{t('connectData.system.syncNow')}</ApexButton>}
                <ApexButton size="sm" variant="ghost" icon={Unplug} disabled={busySource === source.source_id} onClick={() => runSourceAction('disconnect', source)}>{t('connectData.system.disconnect')}</ApexButton>
              </div>
            </li>
          ))}
        </ul>
      ) : <EmptyState title={t('connectData.empty.title')} description={t('connectData.empty.description')} action={<Button size="sm" onClick={() => setAddOpen(true)}>{t('connectData.actions.addSource')}</Button>} />}
    </section>

    {providerSource && <ProviderRecordsPanel key={providerSource.source_id} source={providerSource}
      refreshVersion={`${providerSource.last_run?.job_id || ''}:${providerSource.last_run?.status || ''}`} t={t} />}

    <section ref={uploadRef} className="connect-data-section connect-data-upload">
      <div className="connect-data-section__header"><div><h2>{t('connectData.upload.title')}</h2><p>{t('connectData.upload.subtitle')}</p></div></div>
      <div className="connect-data-upload__grid">
        <div><h3>{t('connectData.upload.templates')}</h3><div className="ceopro-template-options">{DATA_TEMPLATE_OPTIONS.map((template) => <button className="ceopro-template-option" type="button" key={template.id} onClick={() => downloadTemplate(template)}><img src={template.icon} alt="" /><strong>{t(template.labelKey)}</strong><span>{downloadedTemplates.includes(template.id) ? <Check size={14} /> : <Download size={14} />}{t(downloadedTemplates.includes(template.id) ? 'dataIngestion.templates.downloaded' : 'dataIngestion.templates.download')}</span></button>)}</div></div>
        <div><h3>{t('connectData.upload.files')}</h3><FileUploadDropzone files={files} onFilesChange={setFiles} />{files.length > 0 && <Button className="connect-data-prepare" size="sm" onClick={prepareImport} loading={importing} loadingLabel={t('connectData.actions.preparingImport')}>{t('connectData.actions.prepareImport')}</Button>}</div>
      </div>
    </section>
      <StructuredBusinessImport/>


    <ImportDraftsPanel t={t} locale={locale} />

    <section className="connect-data-section">
      <div className="connect-data-section__header"><div><h2>{t('connectData.activity.title')}</h2><p>{t('connectData.activity.subtitle')}</p></div></div>
      {data.recentImports.length ? <div className="connect-data-table-wrap" tabIndex={0} role="region" aria-label={t('common.scrollableTable')}><table className="connect-data-table"><thead><tr><th>{t('connectData.activity.date')}</th><th>{t('connectData.activity.source')}</th><th>{t('connectData.activity.name')}</th><th>{t('connectData.activity.type')}</th><th>{t('connectData.activity.status')}</th></tr></thead><tbody>{data.recentImports.map((item) => <tr key={item.id}><td>{formatDate(item.date)}</td><td>{localize(item.source)}</td><td>{localize(item.name)}</td><td>{t(`connectData.fileTypes.${item.type}`)}</td><td><ConnectionStatusBadge status={item.status} t={t} /></td></tr>)}</tbody></table></div> : <EmptyState title={t('connectData.activity.emptyTitle')} description={t('connectData.activity.emptyDescription')} />}
    </section>

    <CustomerReviewsSection t={t} locale={locale} />

    <Modal isOpen={addOpen} onClose={closeAdd} title={connectKind ? t(connectKind === 'woocommerce' || connectKind === 'shopify' ? `connectData.store.${connectKind}Title` : `connectData.system.${connectKind}Title`) : t('connectData.add.title')} closeLabel={t('common.close')} maxWidth="760px">
      {connectKind === 'woocommerce' || connectKind === 'shopify' ? <ConnectStoreForm provider={connectKind} t={t} onDone={connected} onCancel={() => setConnectKind(null)} />
        : connectKind ? <ConnectSystemForm kind={connectKind} t={t} onDone={connected} onCancel={() => setConnectKind(null)} /> : (
        <>
          <p className="connect-data-modal-copy">{t('connectData.add.subtitle')}</p>
          <div className="connect-options">
            {ADD_OPTIONS.map(({ kind, icon: Icon }) => (
              <button key={kind} type="button" className="connect-option" onClick={() => chooseOption(kind)}>
                <Icon size={22} aria-hidden="true" />
                <strong>{t(kind === 'woocommerce' || kind === 'shopify' ? `connectData.store.options.${kind}.title` : `connectData.options.${kind}.title`)}</strong>
                <span>{t(kind === 'woocommerce' || kind === 'shopify' ? `connectData.store.options.${kind}.description` : `connectData.options.${kind}.description`)}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </Modal>

    {notice && <div className="connect-data-toast"><Toast variant={notice.variant} message={notice.message} onClose={() => setNotice(null)} /></div>}
  </div>;
}
