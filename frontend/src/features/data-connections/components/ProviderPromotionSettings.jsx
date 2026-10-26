import {useState} from 'react';
import Button from '../../../shared/components/ui/Button.jsx';
import {dataConnectionsApi} from '../api/dataConnectionsApi.js';

export function ProviderPromotionSettings({source,t}){
  const [settings,setSettings]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState(null),[result,setResult]=useState(null);
  const load=async()=>{setBusy(true);setError(null);try{setSettings(await dataConnectionsApi.providerPromotionSettings(source.source_id));}catch{setError(t('connectData.providerRecords.loadFailed'));}finally{setBusy(false);}};
  const change=async(category,enabled)=>{
    if(!globalThis.confirm(t('connectData.providerRecords.promotionConfirm')))return;
    setBusy(true);setError(null);
    try{setSettings(await dataConnectionsApi.setProviderPromotion(source.source_id,{category,enabled}));}
    catch(e){setError(t(e.response?.status===403?'connectData.providerRecords.forbidden':'connectData.providerRecords.reviewFailed'));}
    finally{setBusy(false);}
  };
  const retry=async()=>{if(!globalThis.confirm(t('connectData.providerRecords.promotionConfirm')))return;setBusy(true);setError(null);try{setResult(await dataConnectionsApi.retryProviderPromotion(source.source_id));}catch{setError(t('connectData.providerRecords.reviewFailed'));}finally{setBusy(false);}};
  return <div className="provider-records__promotion"><Button size="sm" variant="outline" disabled={busy} onClick={load}>{t('connectData.providerRecords.promotionSettings')}</Button>
    {error&&<p role="alert">{error}</p>}{settings&&<fieldset disabled={busy||!settings.can_change||!settings.disposable_runtime_enabled}><legend>{t('connectData.providerRecords.promotionSettings')}</legend>
      <p>{t('connectData.providerRecords.promotionBoundary')}</p>{!settings.disposable_runtime_enabled&&<p>{t('connectData.providerRecords.promotionDisabled')}</p>}
      {['catalog','inventory'].map(category=><label key={category}><input type="checkbox" checked={settings.categories[category]} onChange={e=>change(category,e.target.checked)}/>{t(`connectData.providerRecords.promotionCategories.${category}`)}</label>)}
      <label><input type="checkbox" checked={false} disabled readOnly/>{t('connectData.providerRecords.promotionCategories.orders')}</label><p>{t('connectData.providerRecords.promotionOrdersBlocked')}</p><Button size="sm" variant="outline" onClick={retry}>{t('connectData.providerRecords.promotionRetry')}</Button>{result&&<p role="status">{t('connectData.providerRecords.promotionResult', {created:result.catalog_created,stock:result.stock_updated,held:result.held?.length||0})}</p>}
    </fieldset>}
  </div>;
}
