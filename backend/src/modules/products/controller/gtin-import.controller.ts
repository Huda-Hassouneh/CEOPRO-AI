import multer from 'multer';
import type {Response,NextFunction} from 'express';
import type {AppRequest} from '../../../types/request.js';
import {sendApiError} from '../../../utils/http.js';
import {ProductError} from '../types/products.types.js';
import {productsRepo} from '../repo/products.repo.js';
import {parseGtinImport,GTIN_IMPORT_BYTES} from '../service/gtin-import.js';
const upload=multer({storage:multer.memoryStorage(),limits:{fileSize:GTIN_IMPORT_BYTES,files:1,fields:0,parts:1}}).single('file');
export function gtinFile(req:AppRequest,res:Response,next:NextFunction){
 upload(req,res,error=>error ? sendApiError(res,'INVALID_PARAMETER',{details:{reason:'GTIN_IMPORT_FILE'}}):next());
}
export const handleGtinImport=(operation:'preview'|'apply')=>async(req:AppRequest,res:Response,next:NextFunction)=>{
 try{
  if(!req.tenant_id || !req.user?.id)return sendApiError(res,'TENANT_ACCESS_DENIED');
  const scope={tenantId:req.tenant_id,userId:req.user.id};
  if(operation==='preview' && !req.file)return sendApiError(res,'INVALID_PARAMETER',{details:{reason:'GTIN_IMPORT_FILE'}});
  const result=operation==='preview' ? await productsRepo.previewGtins(scope,parseGtinImport(req.file!)) : await productsRepo.applyGtins(scope,req.body);
  return res.json({status:'success',data:result});
 }catch(error){if(error instanceof ProductError)return sendApiError(res,error.code,{details:error.details});next(error);}
};
