import MarketingContentBoard from '../components/ContentGeneratorForm.jsx';
import CreativeAssetGenerator from '../components/MarketingImagePreview.jsx';

export default function MarketingPage() {
  return (
    <div className="page">
      <header>
        <h1>Marketing Center</h1>
      </header>
      <MarketingContentBoard />
      <CreativeAssetGenerator />
    </div>
  );
}
