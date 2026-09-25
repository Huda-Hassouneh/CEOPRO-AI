import MarketingContentBoard from '../components/ContentGeneratorForm.jsx';
import CreativeAssetGenerator from '../components/MarketingImagePreview.jsx';
import { FeatureGate } from '../../billing/components/FeatureGate.jsx';

export default function MarketingPage() {
  return (
    <div className="page">
      <header>
        <h1>Marketing Center</h1>
      </header>
      <MarketingContentBoard />
      <FeatureGate featureCode="marketing_image_generation" mode="consume" compact>
        <CreativeAssetGenerator />
      </FeatureGate>
    </div>
  );
}
