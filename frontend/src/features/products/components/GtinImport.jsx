import { translateCurrent } from '../../../shared/lib/i18n.js';
import {useState} from 'react';
import {useMutation} from '@tanstack/react-query';
import Button from '../../../shared/components/ui/Button.jsx';
import {getApiErrorMessage} from '../../../shared/lib/apiErrorCore.js';
import {productsApi} from '../api/productsApi.js';
import {useCatalogMutation} from '../hooks/useCatalog.js';
import {useAuthStore} from '../../auth/store/authStore.js';
export function GtinImport({t,locale}){
 const tenant=useAuthStore(s=>s.tenantId);
 const [file,setFile]=useState(null),[rows,setRows]=useState(null),[localError,setLocalError]=useState('');
 const save=useCatalogMutation('applyGtins');
 const preview=useMutation({mutationFn:async()=>{
  if(useAuthStore.getState().tenantId!==tenant)throw new Error(translateCurrent("interfaceCopy.sessionChangedReloadThisPage"));
  return productsApi.previewGtins(file);
 },onSuccess:data=>{if(useAuthStore.getState().tenantId===tenant)setRows(data.rows);}});
 const busy=preview.isPending||save.isPending;
 const error=preview.error||save.error;
 const errorText=error && (error.response?.data?.error?.details?.reason?.startsWith('GTIN_IMPORT') || error.response?.data?.details?.reason?.startsWith('GTIN_IMPORT')) ? t('catalog.gtin.fileError') : error ? getApiErrorMessage(error,t) : '';
 return <details className="catalog-panel"><summary>{t('catalog.gtin.title')}</summary>
  <div className="catalog-form">
   <p>{t('catalog.gtin.instructions')}</p>
   <a href="data:text/csv;charset=utf-8,sku%2Cgtin%0A" download="product-gtin-template.csv">{t('catalog.gtin.template')}</a>
   <label>{t('catalog.gtin.file')}<input type="file" accept=".csv,.xlsx" disabled={busy} onChange={e=>{setFile(e.target.files?.[0]||null);setRows(null);setLocalError('');preview.reset();save.reset();}} /></label>
   <Button type="button" disabled={busy} onClick={()=>{
    if(!file){setLocalError(t('catalog.gtin.empty'));return;}
    if(file.size===0 || file.size>256*1024 || !/\.(csv|xlsx)$/i.test(file.name)){setLocalError(t('catalog.gtin.limit'));return;}
    setRows(null);setLocalError('');save.reset();preview.mutate();
   }}>{t(busy?'catalog.saving':'catalog.gtin.preview')}</Button>
   {(localError||errorText) && <p role="alert" className="catalog-error">{localError||errorText}</p>}
   {rows && <><div className="catalog-table-wrap"><table><thead><tr><th>{t('catalog.fields.name')}</th><th>{t("interfaceCopy.sku")}</th><th>{t('catalog.gtin.current')}</th><th>{t('catalog.gtin.next')}</th></tr></thead><tbody>
    {rows.map(row=><tr key={row.productId}><td>{typeof row.name==='string'?row.name:row.name?.[locale]||row.name?.en||row.name?.ar}</td><td dir="ltr">{row.sku}</td><td dir="ltr">{row.currentGtin||'—'}</td><td><span dir="ltr">{row.gtin}</span>{row.duplicate && <p className="catalog-note">{t('catalog.gtin.duplicate')}</p>}</td></tr>)}
   </tbody></table></div><Button type="button" disabled={busy} onClick={()=>save.mutate({rows:rows.map(({productId,expectedVersion,gtin})=>({productId,expectedVersion,gtin}))},{onSuccess:()=>setRows(null)})}>{t(save.isPending?'catalog.saving':'catalog.gtin.apply')}</Button></>}
   {save.isSuccess && <p role="status">{t('catalog.gtin.success')}</p>}
  </div>
 </details>;
}
