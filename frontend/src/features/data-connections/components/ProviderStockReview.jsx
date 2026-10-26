import {useState} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import Button from '../../../shared/components/ui/Button.jsx';
import Modal from '../../../shared/components/ui/Modal.jsx';
import {dataConnectionsApi} from '../api/dataConnectionsApi.js';

export function ProviderStockReview({source,t}){
  const client=useQueryClient();const [items,setItems]=useState(null);const [busy,setBusy]=useState(false);const [error,setError]=useState(null);const [selected,setSelected]=useState(null);const [saved,setSaved]=useState(false);
  const load=async()=>{setBusy(true);setError(null);try{setItems((await dataConnectionsApi.reviewProviderStock(source.source_id)).items);}catch(e){setError(t(e.response?.status===403?'connectData.providerRecords.forbidden':'connectData.providerRecords.loadFailed'));}finally{setBusy(false);}};
  const confirm=async()=>{
    setBusy(true);setError(null);setSaved(false);
    try{
      await dataConnectionsApi.postProviderStock(source.source_id,{observation_id:selected.observation_id,preview_hash:selected.preview_hash});setSelected(null);setSaved(true);
      for(const key of ['products','inventory','product-catalog','dashboard-aggregate'])await client.invalidateQueries({queryKey:[key]});
      await load();
    }catch(e){setError(t(e.response?.status===409?'connectData.providerRecords.conflict':'connectData.providerRecords.reviewFailed'));}
    finally{setBusy(false);}
  };
  return <div className="provider-records__stock">
    <Button size="sm" variant="outline" disabled={busy} onClick={load}>{t('connectData.providerRecords.stockReview')}</Button>
    {error&&<p role="alert">{error}</p>}{saved&&<p role="status">{t('connectData.providerRecords.stockSaved')}</p>}
    {items&&<><p>{t('connectData.providerRecords.stockBoundary')}</p>{items.length===0?<p>{t('connectData.providerRecords.stockEmpty')}</p>:<div className="connect-data-table-wrap"><table className="connect-data-table"><thead><tr><th>{t('connectData.providerRecords.stockLocation')}</th><th>{t('connectData.providerRecords.stockField')}</th><th>{t('connectData.providerRecords.stockPrevious')}</th><th>{t('connectData.providerRecords.stockNext')}</th><th>{t('connectData.providerRecords.actions')}</th></tr></thead><tbody>{items.map(item=><tr key={item.observation_id}><td dir="ltr">{item.warehouse}</td><td dir="ltr">{t(`connectData.providerRecords.stockFields.${item.quantity_semantics}`)}</td><td>{item.previous??t('catalog.unknown')}</td><td>{item.quantity}</td><td>{item.reasons.map(reason=><p key={reason}>{t(`connectData.providerRecords.stockFindings.${reason}`)}</p>)}<Button size="sm" disabled={!item.eligible||busy} onClick={()=>setSelected(item)}>{t('connectData.providerRecords.stockSelect')}</Button></td></tr>)}</tbody></table></div>}</>}
    <Modal isOpen={Boolean(selected)} title={t('connectData.providerRecords.stockSelect')} closeLabel={t('common.close')} onClose={()=>{if(!busy)setSelected(null);}}>{selected&&<><p>{t('connectData.providerRecords.stockBoundary')}</p><p dir="ltr">{selected.warehouse}: {selected.previous??t('catalog.unknown')} {'\u2192'} {selected.quantity} ({t(`connectData.providerRecords.stockFields.${selected.quantity_semantics}`)})</p><Button disabled={busy} onClick={confirm}>{t('connectData.providerRecords.stockConfirm')}</Button></>}</Modal>
  </div>;
}
