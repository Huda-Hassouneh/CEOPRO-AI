import { Bot, ChartNoAxesCombined, Telescope } from 'lucide-react';
import SelectableCard from '../../../shared/components/ui/SelectableCard.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { objectiveTypes } from '../types/onboarding.types.js';

const icons = { competitors: Telescope, forecasting: ChartNoAxesCombined, knowledge: Bot };

export function GoalsMultiSelect({ values, onToggle }) {
  const { t } = useI18n();

  return (
    <fieldset className="ceopro-objective-list">
      <legend className="ceopro-visually-hidden">{t('onboarding.objectives.title')}</legend>
      {objectiveTypes.map((objective) => {
        const Icon = icons[objective];
        return (
          <SelectableCard
            key={objective}
            className="ceopro-objective-card"
            type="checkbox"
            name="objectives"
            value={objective}
            checked={values.includes(objective)}
            onChange={() => onToggle(objective)}
            title={t(`onboarding.objectives.options.${objective}.title`)}
            description={t(`onboarding.objectives.options.${objective}.description`)}
            icon={<Icon size={20} />}
          />
        );
      })}
    </fieldset>
  );
}
