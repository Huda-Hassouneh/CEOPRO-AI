import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export default function CreativeAssetGenerator() {
  const { t: copyT } = useI18n();
  return (
    <section className="panel">
      <h2>{copyT("interfaceCopy.creativeAssetGenerator")}</h2>
      <p>{copyT("interfaceCopy.ideasImagePromptsAndCampaignVisualAssets")}</p>
    </section>
  );
}
