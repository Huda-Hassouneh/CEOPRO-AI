import { PointList, SectionHeading, useLanding } from '../components/LandingPrimitives.jsx';
import { ConnectionVisual, IngestionVisual, RagVisual } from '../components/MarketingVisuals.jsx';

export function KnowledgeSections() {
  const { t } = useLanding();
  return <>
    <section className="lp-section" id="rag"><div className="lp-container lp-split lp-split--reverse"><RagVisual /><SectionHeading section="rag"><PointList section="rag" /></SectionHeading></div></section>
    <section className="lp-section lp-tinted" id="data"><div className="lp-container"><SectionHeading section="data" centered /><ConnectionVisual /><p className="lp-fineprint lp-centered">{t('data.note')}</p></div></section>
    <section className="lp-section lp-ingestion-section" id="file-intelligence"><div className="lp-container lp-split"><SectionHeading section="ingestion" /><IngestionVisual /></div></section>
  </>;
}
