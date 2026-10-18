import { Building2, UserRound, UsersRound } from 'lucide-react';
import SelectableCard from '../../../shared/components/ui/SelectableCard.jsx';
import Select from '../../../shared/components/ui/Select.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { annualRevenueRanges, businessSizes } from '../types/onboarding.types.js';

const sizeIcons = [UserRound, UsersRound, Building2];

export function BusinessSizeForm({ businessSize, annualRevenue, onBusinessSizeChange, onAnnualRevenueChange }) {
  const { t } = useI18n();
  const revenueOptions = annualRevenueRanges.map((value) => ({
    value,
    label: t(`onboarding.business.revenueOptions.${value}`),
  }));

  return (
    <div>
      <section className="ceopro-business-section">
        <h2>{t('onboarding.business.sizeLabel')}</h2>
        <p>{t('onboarding.business.sizeHint')}</p>
        <fieldset className="ceopro-setup-card-grid">
          <legend className="ceopro-visually-hidden">{t('onboarding.business.sizeLabel')}</legend>
          {businessSizes.map((size, index) => {
            const Icon = sizeIcons[index];
            return (
              <SelectableCard
                className="ceopro-business-card"
                key={size}
                name="business-size"
                value={size}
                checked={businessSize === size}
                onChange={() => onBusinessSizeChange(size)}
                title={size}
                description={t(`onboarding.business.sizeDescriptions.${index}`)}
                icon={<Icon size={19} />}
              />
            );
          })}
        </fieldset>
      </section>

      <section className="ceopro-business-section">
        <h2>{t('onboarding.business.revenueLabel')}</h2>
        <p>{t('onboarding.business.revenueHint')}</p>
        <Select
          id="annual-revenue"
          value={annualRevenue}
          options={revenueOptions}
          onChange={(event) => onAnnualRevenueChange(event.target.value)}
        />
      </section>
    </div>
  );
}
