import { Bot, Boxes, Database, FileText, Plug, RefreshCw, Target, Users } from 'lucide-react';
import { CustomPlanQuantityField } from './CustomPlanQuantityField.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { CUSTOM_PLAN_LIMITS } from '../config/billingPreviewData.js';

const icons = {
  products: Boxes,
  competitors: Target,
  ragQueries: Bot,
  reports: FileText,
  storageGb: Database,
  teamMembers: Users,
};

export function CustomPlanBuilder({ configuration, onChange }) {
  const { locale, t } = useI18n();
  const formatNumber = (value) => new Intl.NumberFormat(locale === 'ar' ? 'ar-JO' : 'en-US').format(value);

  return (
    <div className="ceopro-custom-plan-controls">
      <div className="ceopro-custom-plan-range-grid">
        {Object.entries(CUSTOM_PLAN_LIMITS).map(([key, limit]) => {
          const Icon = icons[key];
          const unit = key === 'storageGb' ? ' GB' : '';
          return (
            <CustomPlanQuantityField
              key={key}
              label={t(`billing.custom.fields.${key}.label`)}
              description={t(`billing.custom.fields.${key}.description`)}
              value={configuration[key]}
              min={limit.min}
              max={limit.max}
              onChange={(value) => onChange(key, value)}
              formatValue={(value) => `${formatNumber(value)}${unit}`}
              icon={<Icon size={18} />}
            />
          );
        })}
      </div>

      <div className="ceopro-custom-plan-choice-grid">
        <fieldset className="ceopro-custom-choice-card">
          <legend><Plug size={19} aria-hidden="true" /> <span>{t('billing.custom.integrations.label')}</span></legend>
          <small>{t('billing.custom.integrations.description')}</small>
          <div>
            {['none', 'shopify', 'ga4', 'pos', 'other'].map((value) => (
              <label key={value}><input type="radio" name="custom-integrations" checked={configuration.integrations === value} onChange={() => onChange('integrations', value)} />{t(`billing.custom.integrations.options.${value}`)}</label>
            ))}
          </div>
        </fieldset>
        <fieldset className="ceopro-custom-choice-card">
          <legend><RefreshCw size={19} aria-hidden="true" /> <span>{t('billing.custom.frequency.label')}</span></legend>
          <small>{t('billing.custom.frequency.description')}</small>
          <div>
            {['daily', 'hourly', 'realTime'].map((value) => (
              <label key={value}><input type="radio" name="update-frequency" checked={configuration.updateFrequency === value} onChange={() => onChange('updateFrequency', value)} />{t(`billing.custom.frequency.options.${value}`)}</label>
            ))}
          </div>
        </fieldset>
      </div>
    </div>
  );
}
