import {useState} from 'react';
import Button from '../../../shared/components/ui/Button.jsx';

export function DiscoveryCoverage({result,t}) {
  const [page,setPage]=useState(0);
  if(!result?.coverage)return null;
  const products=result.products||[],checked=products.filter(p=>p.outcome!=='NOT_CHECKED').length;
  return <details className="competitor-evidence-row">
    <summary>{t('competitorWorkflow.coverageCount',{checked,unchecked:products.length-checked})}</summary>
    <p>{t('competitorWorkflow.coverage')}</p>
    {products.slice(page*10,page*10+10).map(product=><p key={product.product_id}>
      <strong>{product.product_name||product.product_id}</strong>: {t(`competitorWorkflow.outcomes.${product.outcome}`)}
      {product.candidate_count>0?` (${product.candidate_count})`:''}
    </p>)}
    {products.length>10 && <div className="competitor-management-actions">
      <Button type="button" variant="outline" disabled={page===0} onClick={()=>setPage(v=>v-1)}>{t('competitorWorkflow.previous')}</Button>
      <Button type="button" variant="outline" disabled={(page+1)*10>=products.length} onClick={()=>setPage(v=>v+1)}>{t('competitorWorkflow.next')}</Button>
    </div>}
  </details>;
}
