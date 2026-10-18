import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export default function MarketingContentBoard() {
  const { t: copyT } = useI18n();
  return (
    <section className="panel">
      <h2>{copyT("interfaceCopy.marketingContentBoard")}</h2>
      <p>{copyT("interfaceCopy.creativeBriefsCampaignsAndContentGenerationTasks")}</p>
    </section>
  );
}
