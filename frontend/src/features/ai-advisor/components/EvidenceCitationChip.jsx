import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function EvidenceCitationChip() {
  const { t: copyT } = useI18n();
  return <span className="evidence-citation-chip">{copyT("interfaceCopy.evidence")}</span>;
}
