import { CreditCard } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { routePaths } from '../../../app/router/routePaths.js';
import Button from '../../../shared/components/ui/Button.jsx';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import { SettingsSection } from './SettingsSection.jsx';

export function CompanySettings({ query, permissions, t }) {
  const navigate = useNavigate();
  if (query.isPending) return <Skeleton height="310px" variant="rectangular" />;
  if (query.isError) return <SettingsSection title={t('settings.company.title')}><p className="settings-inline-error">{t('settings.company.loadError')}</p></SettingsSection>;
  const company = query.data.company;
  const fields = ['name', 'industry', 'businessSize', 'country', 'currency'];
  return <SettingsSection title={t('settings.company.title')} subtitle={t('settings.company.subtitle')} actions={permissions.canEditCompany && <Button size="sm" variant="outline" leadingIcon={<CreditCard size={14} />} onClick={() => navigate(routePaths.billing)}>{t('settings.company.manageSubscription')}</Button>}>
    <dl className="settings-readonly-grid">{fields.map((key) => <div key={key}><dt>{t(`settings.company.fields.${key}`)}</dt><dd>{company[key] || t('settings.common.notAvailable')}</dd></div>)}</dl>
    <p className="settings-capability-note">{t(permissions.canEditCompany ? 'settings.company.editUnavailable' : 'settings.company.readOnly')}</p>
  </SettingsSection>;
}
