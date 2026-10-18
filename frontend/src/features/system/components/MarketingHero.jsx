import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export default function MarketingHero() {
  const { t: copyT } = useI18n();
  return (
    <section className="hero">
      <h1>{copyT("interfaceCopy.marketingHero")}</h1>
    </section>
  );
}
