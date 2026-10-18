function localized(value,locale) {
  return typeof value==='string'?value:value?.[locale]||value?.en||value?.ar||'—';
}
export function ProductIdentityEvidence({identity,preview,t,locale}) {
  const formatAttributes=attributes=>attributes?.sizes?.map(([dimension,value])=>`${value} ${t(dimension==='mass'?'common.units.grams':'common.units.milliliters')}`).join(' / ')||t('competitorWorkflow.unknown');
  return <div className="competitor-identity-evidence">
    <div><strong>{t('competitorWorkflow.yourProduct')}</strong>
      <p>{localized(identity?.name,locale)}</p>
      <p>{t('competitorWorkflow.brand')}: {localized(identity?.brand,locale)}</p>
      <p>{t("interfaceCopy.gtin")}{identity?.gtin||'—'}</p>
    </div>
    <div><strong>{t('competitorWorkflow.selectedProduct')}</strong>
      {!preview ? <p>{t('competitorWorkflow.notChecked')}</p> : <>
        <p>{preview.name||preview.observed?.[0]?.name||'—'}</p>
        <p>{t('competitorWorkflow.brand')}: {preview.brand||preview.observed?.[0]?.brand||'—'}</p>
        <p>{t("interfaceCopy.gtin")}{preview.gtinEvidence?.observed_gtin14||'—'}</p>
        <p>{preview.price!=null ? `${preview.price} ${preview.currency}` : t('competitorWorkflow.noPreviewPrice')}</p>
        <p>{t(`competitorWorkflow.reasons.${preview.reason}`)}</p>
        {preview.matchMethod && <p>{t(`competitorWorkflow.methods.${preview.matchMethod}`)}</p>}
        {preview.observed?.flatMap(item=>item.conflicts||[]).map((reason,index)=><p key={`${reason}-${index}`}>{t(`competitorWorkflow.reasons.${reason}`)}</p>)}
        <p>{t('competitorWorkflow.size')}: {formatAttributes(preview.attributes||preview.observed?.[0]?.attributes)}</p>
        <p>{t('competitorWorkflow.pack')}: {(preview.attributes||preview.observed?.[0]?.attributes)?.pack_count??t('competitorWorkflow.unknown')}</p>
        <p>{t('competitorWorkflow.model')}: {(preview.attributes||preview.observed?.[0]?.attributes)?.model||t('competitorWorkflow.unknown')}</p>
        <p>{t('competitorWorkflow.attributesHint')}</p>
      </>}
    </div>
  </div>;
}
