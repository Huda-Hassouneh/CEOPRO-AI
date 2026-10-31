import Table from '../../shared/components/ui/Table.jsx';
import Card from '../../shared/components/ui/Card.jsx';

// Evidence only. No prices, credentials, approval mutations or provider calls.
export function EconomicReadiness({ data, text }) {
  if (!data?.provider_readiness) return null;
  const readiness = data.provider_readiness;
  return <Card><details data-testid="economic-readiness"><summary>{text('catalog.title')}</summary>
    <p>{text('catalog.explanation')}</p><p>{readiness.catalog_version}</p>
    <h4>{text('catalog.coverage')}</h4>
    <Table data={Object.values(data.feature_economics || {})} columns={[
      { header:text('feature'), accessor:'feature_code' },
      { header:text('coverage'), render:r=>text('treatments.'+r.treatment) },
      { header:text('source'), accessor:'source' },
    ]}/>
    <h4>{text('catalog.providers')}</h4><Table data={readiness.providers} columns={[
      { header:text('provider'), render:r=>r.provider+' / '+(r.operation || '—') },
      { header:text('verification'), render:r=>r.rates.map(x=>x.unit+': '+text('rateStatuses.'+x.status)).join(' · ') },
      { header:text('catalog.provenance'), render:r=>r.rates.map(x=>x.provenance?text('catalog.origins.'+x.provenance):'—').join(' · ') },
      { header:text('catalog.credentials'), render:r=>text('catalog.'+r.credential_status) },
      { header:text('catalog.requirements'), render:r=>[...r.missing_settings,...r.approval_requirements].join(' · ') || '—' },
    ]}/>
    <h4>{text('catalog.approvals')}</h4><ul>{readiness.approvals.map(r=><li key={r.setting}>{r.setting}: {text('catalog.'+(r.present?'PRESENT_UNTESTED':'MISSING'))}</li>)}</ul>
    <p>{text('catalog.operational')}</p>
  </details></Card>;
}
