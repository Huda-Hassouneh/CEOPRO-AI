import { useState } from 'react';
import { ArrowLeft, Check, Download, FileSpreadsheet } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import Button from '../../../shared/components/ui/Button.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { FileUploadDropzone } from '../../data-ingestion/components/FileUploadDropzone.jsx';
import { ingestionApi } from '../../data-ingestion/api/ingestionApi.js';
import { DATA_TEMPLATE_OPTIONS } from '../../data-ingestion/config/dataTemplateOptions.js';
import { OnboardingPageShell } from '../components/OnboardingPageShell.jsx';
import { useOnboardingStore } from '../store/onboardingStore.js';

export function OnboardingUploadDocumentsPage() {
  const navigate = useNavigate();
  const { t } = useI18n();
  const [files, setFiles] = useState([]);
  const downloadedTemplates = useOnboardingStore((state) => state.downloadedTemplates);
  const markTemplateDownloaded = useOnboardingStore((state) => state.markTemplateDownloaded);
  const setSourceStatus = useOnboardingStore((state) => state.setSourceStatus);
  const hasDownloadedTemplate = downloadedTemplates.length > 0;

  const updateFiles = (nextFiles) => {
    setFiles(nextFiles);
    setSourceStatus('documents', nextFiles.length > 0 && hasDownloadedTemplate ? 'connected' : 'not-connected');
  };

  const requestTemplate = async (templateId) => {
    const result = await ingestionApi.downloadTemplate(templateId);
    if (!result.url) return;

    const download = document.createElement('a');
    download.href = result.url;
    download.download = result.filename;
    document.body.appendChild(download);
    download.click();
    download.remove();

    markTemplateDownloaded(templateId);
    if (files.length > 0) setSourceStatus('documents', 'connected');
  };

  return (
    <OnboardingPageShell wide showProgress={false}>
      <div className="ceopro-upload-panel">
        <Link className="ceopro-subpage-back" to={routePaths.onboardingConnectData}><ArrowLeft className="ceopro-setup-direction-icon" size={14} />{t('dataIngestion.back')}</Link>
        <header className="ceopro-setup-page__heading">
          <span className="ceopro-data-source-card__icon"><FileSpreadsheet size={27} /></span>
          <h1>{t('dataIngestion.title')}</h1>
        </header>
        <section className="ceopro-upload-step" aria-labelledby="template-step-title">
          <header className="ceopro-upload-step__heading">
            <span aria-hidden="true">1</span>
            <div><h2 id="template-step-title">{t('dataIngestion.templateTitle')}</h2><p>{t('dataIngestion.templateDescription')}</p></div>
          </header>
          <div className="ceopro-template-options">
            {DATA_TEMPLATE_OPTIONS.map((template) => {
              const downloaded = downloadedTemplates.includes(template.id);
              return (
                <button className="ceopro-template-option" type="button" key={template.id} onClick={() => requestTemplate(template.id)}>
                  <img src={template.icon} alt="" aria-hidden="true" />
                  <strong>{t(template.labelKey)}</strong>
                  <span>{downloaded ? <Check size={14} /> : <Download size={14} />}{t(downloaded ? 'dataIngestion.templates.downloaded' : 'dataIngestion.templates.download')}</span>
                </button>
              );
            })}
          </div>
        </section>
        <section className="ceopro-upload-step" aria-labelledby="upload-step-title">
          <header className="ceopro-upload-step__heading">
            <span aria-hidden="true">2</span>
            <div><h2 id="upload-step-title">{t('dataIngestion.uploadTitle')}</h2><p>{t('dataIngestion.uploadDescription')}</p></div>
          </header>
          <FileUploadDropzone files={files} onFilesChange={updateFiles} />
          {files.length > 0 && !hasDownloadedTemplate && <p className="ceopro-template-required" role="status">{t('dataIngestion.templateRequired')}</p>}
        </section>
      </div>
      <OnboardingActionsShim onBack={() => navigate(routePaths.onboardingConnectData)} />
    </OnboardingPageShell>
  );
}

function OnboardingActionsShim({ onBack }) {
  const { t } = useI18n();
  return <div className="ceopro-setup-actions"><Button variant="outline" onClick={onBack}>{t('onboarding.common.back')}</Button></div>;
}
