import {useState} from 'react';
import Button from '../../../shared/components/ui/Button.jsx';
import {dataConnectionsApi} from '../api/dataConnectionsApi.js';
import {storeErrorMessage} from './WebsiteStoreSetup.jsx';

/** Reports contain only KEEL's source-linked order accounting, not customer identity. */
export default function ShopifyPrivacyReports({sourceId,t}){
 const [busy,setBusy]=useState(false),[message,setMessage]=useState('');
 const download=async()=>{
  setBusy(true);setMessage('');
  try{
   const reports=await dataConnectionsApi.storePrivacyReports(sourceId);
   if(!reports.length){setMessage(t('storeConnection.shopify.noPrivacyReports'));return;}
   const url=URL.createObjectURL(new Blob([JSON.stringify(reports,null,2)],{type:'application/json'}));
   const link=document.createElement('a');link.href=url;link.download='shopify-data-request-reports.json';link.click();
   setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(error){setMessage(storeErrorMessage(error,t));}
  finally{setBusy(false);}
 };
 return <div><Button variant="outline" loading={busy} onClick={download}>{t('storeConnection.shopify.privacyReports')}</Button>
  {message&&<p role="status">{message}</p>}</div>;
}
