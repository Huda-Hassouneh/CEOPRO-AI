import { useState } from 'react';
import { Download, Trash2 } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import httpClient from '../../../shared/lib/httpClient.js';
import { useAuthStore } from '../../auth/store/authStore.js';
import { ApexButton } from '../../../shared/components/apex/Apex.jsx';
import { SettingsSection } from './SettingsSection.jsx';

// The company's own data: download all of it, or delete the company for good.
export function CompanyDataSettings({ permissions, companyName, t }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const clearSession = useAuthStore((state) => state.clearSession);
  const [exporting, setExporting] = useState(false);
  const [confirm, setConfirm] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [message, setMessage] = useState(null);
  if (!permissions.canExportCompany && !permissions.canDeleteCompany) return null;

  const download = async () => {
    setExporting(true);
    setMessage(null);
    try {
      const response = await httpClient.get('/settings/company/export', { responseType: 'blob' });
      const url = URL.createObjectURL(response.data);
      const link = document.createElement('a');
      link.href = url;
      link.download = `keel-company-export-${new Date().toISOString().slice(0, 10)}.zip`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch {
      setMessage({ tone: 'error', key: 'settings.data.exportFailed' });
    } finally {
      setExporting(false);
    }
  };

  const matches = confirm.trim().replace(/\s+/g, ' ').toLocaleLowerCase() === (companyName || '').trim().replace(/\s+/g, ' ').toLocaleLowerCase();
  const remove = async () => {
    if (!matches || deleting) return;
    setDeleting(true);
    setMessage(null);
    try {
      await httpClient.delete('/settings/company', { data: { confirm_name: confirm } });
      clearSession();
      navigate('/login', { replace: true, state: { authNotice: 'company-deleted' } });
      setTimeout(() => queryClient.clear(), 0);
    } catch (error) {
      const code = error?.response?.data?.detail?.code;
      setMessage({ tone: 'error', key: code === 'SUBSCRIPTION_ACTIVE' ? 'settings.data.subscriptionActive' : 'settings.data.deleteFailed' });
      setDeleting(false);
    }
  };

  return (
    <SettingsSection title={t('settings.data.title')} subtitle={t('settings.data.subtitle')}>
      {permissions.canExportCompany && (
        <div className="settings-data-row">
          <div><strong>{t('settings.data.exportTitle')}</strong><p>{t('settings.data.exportText')}</p></div>
          <ApexButton variant="secondary" icon={Download} loading={exporting} onClick={download}>{t('settings.data.exportButton')}</ApexButton>
        </div>
      )}
      {permissions.canDeleteCompany && (
        <div className="settings-data-row settings-data-row--danger">
          <div>
            <strong>{t('settings.data.deleteTitle')}</strong>
            <p>{t('settings.data.deleteText')}</p>
            <label className="setup-field">
              <span>{t('settings.data.confirmLabel', { name: companyName })}</span>
              <input className="apex-input" value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder={companyName} autoComplete="off" />
            </label>
          </div>
          <ApexButton variant="danger" icon={Trash2} loading={deleting} disabled={!matches} onClick={remove}>{t('settings.data.deleteButton')}</ApexButton>
        </div>
      )}
      {message && <p className="settings-inline-error" role="alert">{t(message.key)}</p>}
    </SettingsSection>
  );
}

export default CompanyDataSettings;
