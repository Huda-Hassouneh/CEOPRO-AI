import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import MarketingContentBoard from '../components/ContentGeneratorForm.jsx';
import CreativeAssetGenerator from '../components/MarketingImagePreview.jsx';
import { FeatureGate } from '../../billing/components/FeatureGate.jsx';

export default function MarketingPage() {
  const { t: copyT } = useI18n();
  return (
    <div className="page">
      <header>
        <h1>{copyT("interfaceCopy.marketingCenter")}</h1>
      </header>
      <MarketingContentBoard />
      <FeatureGate featureCode="marketing_image_generation" mode="consume" compact>
        <CreativeAssetGenerator />
      </FeatureGate>
    </div>
  );
}
