import {useState} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {useI18n} from '../../../app/providers/I18nProvider.jsx';
import {ingestionApi} from '../api/ingestionApi.js';
import {FileUploadDropzone} from './FileUploadDropzone.jsx';
import {StructuredImportReview} from './StructuredImportReview.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import httpClient from '../../../shared/lib/httpClient.js';
import '../styles/StructuredImport.css';
// Original review/choices/confirmation component; existing sales and KB flows stay separate.
export function StructuredBusinessImport(){
 const {t,locale}=useI18n(),queries=useQueryClient();
 const [kind,setKind]=useState('inventory'),[files,setFiles]=useState([]),[preview,setPreview]=useState(null),[review,setReview]=useState(null),[choices,setChoices]=useState({}),[busy,setBusy]=useState(false),[error,setError]=useState(''),[result,setResult]=useState(null);
 const run=async action=>{setBusy(true);setError('');try{await action();}catch(e){setReview(null);setError(typeof e.response?.data?.detail==='string'?e.response.data.detail:t('connectData.review.previewFailed'));}finally{setBusy(false);}};
 const download=async format=>{const response=await httpClient.get(`/extraction/structured-imports/templates/${kind}/${format}`,{responseType:'blob'}),url=URL.createObjectURL(response.data),a=document.createElement('a');a.href=url;a.download=`keel-${kind}.${format}`;a.click();URL.revokeObjectURL(url);};
 return <section className="connect-data-import structured-business-import"><h3>{t('connectData.review.title')}</h3>
 <label>{t('connectData.review.sheets')}<select value={kind} disabled={busy||Boolean(preview)} onChange={e=>{setKind(e.target.value);setFiles([]);setResult(null);}}><option value="inventory">{t('connectData.review.balances',{count:''})}</option><option value="invoices">{t('connectData.review.invoices',{count:''})}</option></select></label>
 {!preview&&<><div className="catalog-actions">{['csv','xlsx'].map(format=><Button key={format} size="sm" variant="outline" disabled={busy} onClick={()=>run(()=>download(format))}>{format.toUpperCase()}</Button>)}</div><FileUploadDropzone files={files} onFilesChange={setFiles}/><Button disabled={files.length!==1||busy} loading={busy} onClick={()=>run(async()=>{setPreview(await ingestionApi.previewBusinessImport(files[0],kind));setChoices({});setResult(null);})}>{t('connectData.actions.prepareImport')}</Button></>}
 {error&&<p role="alert">{error}</p>}
 {preview&&<StructuredImportReview preview={preview} choices={choices} review={review} busy={busy} locale={locale} t={t} onCancel={()=>{setPreview(null);setReview(null);setChoices({});}} onChoice={(match,value)=>{setChoices(c=>({...c,[match.key]:value}));setReview(null);}} onReview={()=>run(async()=>setReview(await ingestionApi.reviewBusinessImport(kind,preview.draftId,choices)))} onConfirm={()=>run(async()=>{const saved=await ingestionApi.confirmBusinessImport(kind,preview.draftId,choices,review.reviewHash);setResult(saved);setPreview(null);setReview(null);setFiles([]);for(const key of ['data-connections','products','dashboard-aggregate','demand-prediction'])await queries.invalidateQueries({queryKey:[key]});})}/>}
 {result&&<p role="status">{t('connectData.review.imported',{invoices:result.kind==='invoices'?result.imported:0,items:result.invoiceItems,inventory:result.kind==='inventory'?result.imported+result.updated:0})}</p>}
 </section>;
}
