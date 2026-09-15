import { Factory, HeartPulse, Laptop, Shapes, Store, UtensilsCrossed } from 'lucide-react';
import SelectableCard from '../../../shared/components/ui/SelectableCard.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { onboardingIndustries } from '../types/onboarding.types.js';

const icons = {
  retail: Store,
  tech: Laptop,
  manufacturing: Factory,
  restaurants: UtensilsCrossed,
  healthcare: HeartPulse,
  other: Shapes,
};

export function IndustryPicker({ value, onChange }) {
  const { t } = useI18n();

  return (
    <fieldset className="ceopro-setup-card-grid">
      <legend className="ceopro-visually-hidden">{t('onboarding.industry.title')}</legend>
      {onboardingIndustries.map((industry) => {
        const Icon = icons[industry];
        return (
          <SelectableCard
            className="ceopro-industry-card"
            key={industry}
            name="industry"
            value={industry}
            checked={value === industry}
            onChange={() => onChange(industry)}
            title={t(`onboarding.industry.options.${industry}`)}
            icon={<Icon size={21} strokeWidth={1.8} />}
          />
        );
      })}
    </fieldset>
  );
}
