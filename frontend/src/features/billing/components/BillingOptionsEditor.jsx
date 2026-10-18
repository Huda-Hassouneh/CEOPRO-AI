import { Plus } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';
import Input from '../../../shared/components/ui/Input.jsx';
import Select from '../../../shared/components/ui/Select.jsx';

export default function BillingOptionsEditor({ options, onChange, baseUnit = 'month', t }) {
  const updateOption = (index, key, value) => {
    onChange(options.map((option, optionIndex) => (
      optionIndex === index ? { ...option, [key]: value } : option
    )));
  };

  return (
    <div className="billing-catalog-subsection">
      <div className="billing-catalog-subsection-header">
        <div>
          <h3>{t('billing.catalog.plans.billingOptions')}</h3>
          <p>{t('billing.catalog.plans.billingOptionsHelp')}</p>
        </div>
        <Button
          variant="outline"
          size="sm"
          leadingIcon={<Plus size={14} />}
          onClick={() => onChange([...options, { period: '', intervalUnit: baseUnit,
            intervalCount: 1, discountPercent: 0 }])}
        >
          {t('billing.catalog.plans.addBillingOption')}
        </Button>
      </div>
      <div className="billing-catalog-option-list">
        {options.map((option, index) => (
          <div className="billing-catalog-option-row" key={`${option.period}-${index}`}>
            <Input label={t('billing.catalog.fields.periodCode')} value={option.period} onChange={(event) => updateOption(index, 'period', event.target.value)} required />
            <Select label={t('billing.catalog.fields.intervalUnit')} value={option.intervalUnit}
              onChange={(event) => onChange(options.map((entry, entryIndex) => entryIndex === index
                ? { ...entry, intervalUnit: event.target.value, intervalCount: 1 } : entry))}
              options={(baseUnit === 'day' ? ['day'] : ['month', 'year']).map((unit) => ({
                value: unit, label: t(`billing.catalog.intervalUnits.${unit}`)
              }))} />
            <Input label={t('billing.catalog.fields.intervalValue')} type="number" min="1" step="1"
              value={option.intervalCount} onChange={(event) => updateOption(index, 'intervalCount', event.target.value)} required />
            <Input label={t('billing.catalog.fields.discountPercent')} type="number" min="0" max="100" step="0.01" value={option.discountPercent} onChange={(event) => updateOption(index, 'discountPercent', event.target.value)} required />
            <Button
              variant="ghost"
              size="sm"
              disabled={options.length === 1}
              onClick={() => onChange(options.filter((_, optionIndex) => optionIndex !== index))}
            >
              {t('common.remove')}
            </Button>
          </div>
        ))}
      </div>
    </div>
  );
}
