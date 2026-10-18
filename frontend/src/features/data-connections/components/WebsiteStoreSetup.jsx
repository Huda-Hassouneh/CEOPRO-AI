import {useEffect,useState} from 'react';
import Modal from '../../../shared/components/ui/Modal.jsx';
import Input from '../../../shared/components/ui/Input.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import Select from '../../../shared/components/ui/Select.jsx';
import {dataConnectionsApi} from '../api/dataConnectionsApi.js';
import {storeErrorMessage} from '../utils/connectionPresentation.js';
export {storeErrorMessage} from '../utils/connectionPresentation.js';
export default function WebsiteStoreSetup({isOpen,initialUrl,sourceId,onClose,onConnected,t}){
 const [url,setUrl]=useState(initialUrl||''),[detected,setDetected]=useState(null),[key,setKey]=useState(''),[secret,setSecret]=useState('');
 const [includeTests,setIncludeTests]=useState(false),[consent,setConsent]=useState(false),[minutes,setMinutes]=useState('60'),[busy,setBusy]=useState(false),[error,setError]=useState('');
 useEffect(()=>{setUrl(initialUrl||'');setDetected(null);setKey('');setSecret('');setConsent(false);setIncludeTests(false);setError('');},[isOpen,initialUrl]);
 const detect=async event=>{event.preventDefault();setBusy(true);setError('');try{setDetected(await dataConnectionsApi.detectStore(url));}catch(e){setError(storeErrorMessage(e,t));}finally{setBusy(false);}};
 const connectShopify=async event=>{event.preventDefault();setBusy(true);setError('');try{const result=await dataConnectionsApi.authorizeShopify({url,...(sourceId?{sourceId}:{}),consent,includeTestOrders:includeTests,syncFrequencyMinutes:Number(minutes)});const target=new URL(result.authorizationUrl);if(target.protocol!=='https:'||!/^[-a-z0-9]+\.myshopify\.com$/.test(target.hostname)||target.pathname!=='/admin/oauth/authorize')throw Error();sessionStorage.setItem('keel.shopify.state',target.searchParams.get('state')||'');window.location.assign(target.href);}catch(e){setError(storeErrorMessage(e,t));setBusy(false);}};
 const connect=async event=>{event.preventDefault();setBusy(true);setError('');try{
  const result=await dataConnectionsApi.connectStore({url:detected.url,consumerKey:key,consumerSecret:secret,consent,syncFrequencyMinutes:Number(minutes)});
  setKey('');setSecret('');await onConnected(result);onClose();
 }catch(e){setError(storeErrorMessage(e,t));}finally{setBusy(false);}};
 const saveUrl=async()=>{setBusy(true);setError('');try{const result=await dataConnectionsApi.configureWebsite({url});await onConnected(result);onClose();}catch(e){setError(storeErrorMessage(e,t));}finally{setBusy(false);}};
 return <Modal isOpen={isOpen} onClose={()=>{if(!busy)onClose();}} title={t('storeConnection.title')} closeLabel={t('storeConnection.close')}>
  <p>{t('storeConnection.description')}</p>
  {!detected?.supported&&<form onSubmit={detect}>
   <Input label={t('storeConnection.url')} type="url" required value={url} disabled={busy} maxLength={2048} onChange={e=>{setUrl(e.target.value);setDetected(null);}} placeholder={t("interfaceCopy.httpsYourStoreCom")}/>
   <Button type="submit" loading={busy} loadingLabel={t('storeConnection.checking')}>{t('storeConnection.detect')}</Button>
   <Button type="button" variant="ghost" disabled={busy||!url.trim()} onClick={()=>{setDetected({supported:true,manual:true,url:url.trim()});setError('');}}>{t('storeConnection.manualWoo')}</Button>
   <Button type="button" variant="ghost" disabled={busy} onClick={()=>{setDetected({supported:true,provider:'shopify',url:url.trim()});setError('');}}>{t('storeConnection.shopify.select')}</Button>
  </form>}
  {detected?.supported&&detected.provider!=='shopify'&&<form onSubmit={connect} autoComplete="off">
   <p role="status">{t(detected.manual?'storeConnection.manualSelected':'storeConnection.detected')} · {detected.url}</p>
   <p>{t('storeConnection.credentialsHint')}</p>
   <StoreAuthorizationFields {...{t,keyValue:key,secret,minutes,consent,busy,setKey,setSecret,setMinutes,setConsent}}/>
   <div className="ceopro-setup-actions"><Button type="button" variant="outline" disabled={busy} onClick={()=>{setDetected(null);setKey('');setSecret('');setConsent(false);}}>{t('storeConnection.changeUrl')}</Button>
    <Button type="submit" loading={busy} loadingLabel={t('storeConnection.verifying')} disabled={!consent}>{t('storeConnection.connect')}</Button></div>
  </form>}
  {detected?.supported&&detected.provider==='shopify'&&<form onSubmit={connectShopify}>
   <ShopifyAuthorizationFields {...{t,url,setUrl,minutes,setMinutes,consent,setConsent,includeTests,setIncludeTests,busy}}/>
   <div className="ceopro-setup-actions"><Button type="button" variant="outline" disabled={busy} onClick={()=>setDetected(null)}>{t('storeConnection.changeUrl')}</Button>
   <Button type="submit" disabled={!consent} loading={busy} loadingLabel={t('storeConnection.shopify.redirecting')}>{t('storeConnection.shopify.connect')}</Button></div>
  </form>}
  {detected&&!detected.supported&&<><p role="status">{t('storeConnection.unsupported')}</p><Button type="button" variant="outline" disabled={busy} onClick={saveUrl}>{t('storeConnection.saveUrlOnly')}</Button></>}
  {error&&<p role="alert" className="ceopro-field-message ceopro-field-message--error">{error}</p>}
 </Modal>;
}

export function StoreAuthorizationFields({t,keyValue,secret,minutes,consent,busy,setKey,setSecret,setMinutes,setConsent}){
 return <>   <Input label={t('storeConnection.key')} type="password" value={keyValue} required autoComplete="new-password" maxLength={43} disabled={busy} onChange={e=>setKey(e.target.value)}/>
   <Input label={t('storeConnection.secret')} type="password" value={secret} required autoComplete="new-password" maxLength={43} disabled={busy} onChange={e=>setSecret(e.target.value)}/>
   <Select label={t('storeConnection.frequency')} value={minutes} disabled={busy} onChange={e=>setMinutes(e.target.value)} options={['15','60','1440'].map(value=>({value,label:t('storeConnection.every'+value)}))}/>
   <label className="ceopro-field-message"><input type="checkbox" required checked={consent} disabled={busy} onChange={e=>setConsent(e.target.checked)}/> {t('storeConnection.consent')}</label>
   <p>{t('storeConnection.importScope')}</p>
   <p>{t('storeConnection.managedHint')}</p>
</>;
}

export function ShopifyAuthorizationFields({t,url,setUrl,minutes,setMinutes,consent,setConsent,includeTests,setIncludeTests,busy}){
 return <>
  <p>{t('storeConnection.shopify.explanation')}</p>
  <Input label={t('storeConnection.shopify.domain')} value={url} required maxLength={100} disabled={busy} onChange={e=>setUrl(e.target.value)} placeholder={t("interfaceCopy.httpsYourStoreMyshopifyCom")}/>
  <Select label={t('storeConnection.frequency')} value={minutes} disabled={busy} onChange={e=>setMinutes(e.target.value)} options={['15','60','1440'].map(value=>({value,label:t('storeConnection.every'+value)}))}/>
  <label className="ceopro-field-message"><input type="checkbox" required checked={consent} disabled={busy} onChange={e=>setConsent(e.target.checked)}/> {t('storeConnection.consent')}</label>
  <label className="ceopro-field-message"><input type="checkbox" checked={includeTests} disabled={busy} onChange={e=>setIncludeTests(e.target.checked)}/> {t('storeConnection.shopify.includeTests')}</label>
  <p>{t('storeConnection.shopify.history')}</p>
  <p>{t('storeConnection.managedHint')}</p>
 </>;
}
