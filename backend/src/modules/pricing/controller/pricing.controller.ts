import type { NextFunction, Response } from "express";
import { ERROR_CODES } from "../../../errors/error-codes.js";
import type { AppRequest } from "../../../types/request.js";
import { successResponse, errorResponse } from "../../../types/response.js";
import {z} from 'zod';
import {FeatureUsageCapacityError,FeatureUsageUnavailableError} from '../../features/repo/usage.repo.js';
import { sendApiError } from "../../../utils/http.js";
import { isPricingClientError } from "../client/pricing.client.js";
import {
  getPricingRecommendation,
  getPricingHistory,
  isPricingServiceError
} from "../service/pricing.service.js";

export async function recommendPrice(
  req: AppRequest,
  res: Response,
  next: NextFunction
): Promise<void> {
  try {
    const tenantId = req.tenant_id;
    const userId = req.user?.user_id;
    const authorization = req.headers.authorization;
    const productId =
      typeof req.query.product_id === "string" ? req.query.product_id : null;

    if (!tenantId || !userId) {
      sendApiError(res, ERROR_CODES.TENANT_ACCESS_DENIED);
      return;
    }

    if (!authorization) {
      sendApiError(res, ERROR_CODES.INVALID_AUTH_HEADER);
      return;
    }

    if (!productId) {
      sendApiError(res, ERROR_CODES.INVALID_PARAMETER);
      return;
    }

    const data = await getPricingRecommendation({
      tenantId,
      userId,
      productId,
      requestId: typeof req.query.request_id==='string'?req.query.request_id:undefined
    });

    res
      .status(200)
      .json(
        successResponse(data, "Pricing recommendation fetched successfully")
      );
  } catch (error) {
    if(handlePricingError(res,error))return;
    if (isPricingServiceError(error)) {
      if (error.code === "PRODUCT_NOT_FOUND") {
        sendApiError(res, ERROR_CODES.RESOURCE_NOT_FOUND, {
          publicMessage: "Product not found"
        });
        return;
      }
    }

    if (isPricingClientError(error)) {
      sendApiError(res, ERROR_CODES.EXTERNAL_SERVICE_ERROR, {
        details: {
          service: "AI pricing service",
          upstream_status: error.upstreamStatus ?? null
        }
      });
      return;
    }

    next(error);
  }
}

function handlePricingError(res:Response,error:unknown):boolean {
  if(error instanceof FeatureUsageCapacityError){sendApiError(res,ERROR_CODES.PAYMENT_REQUIRED,{details:{feature_code:'ai_pricing',reason:'QUOTA_EXHAUSTED'}});return true;}
  if(error instanceof FeatureUsageUnavailableError){sendApiError(res,ERROR_CODES.FORBIDDEN,{details:{feature_code:'ai_pricing',reason:'FEATURE_NOT_INCLUDED'}});return true;}
  if(isPricingServiceError(error)&&error.code!=='PRODUCT_NOT_FOUND'){
    const status=error.code==='INVALID_AI_RESULT'?502:['INVALID_PRODUCT_PRICE','INVALID_REQUEST'].includes(error.code)?400:409;
    res.status(status).json(errorResponse('Pricing request could not be completed.',status,'PRICING_'+error.code,{reason:error.code}));return true;
  }
  return false;
}
export async function listPricingHistory(req:AppRequest,res:Response,next:NextFunction){
  try{
    const productId=typeof req.query.product_id==='string'?req.query.product_id:'';
    if(!req.tenant_id||!req.user?.user_id||!z.uuid().safeParse(productId).success){sendApiError(res,ERROR_CODES.INVALID_PARAMETER);return;}
    res.json(successResponse(await getPricingHistory({tenantId:req.tenant_id,userId:req.user.user_id,productId}),'Pricing history fetched'));
  }catch(error){
    if(handlePricingError(res,error))return;
    if(isPricingServiceError(error)&&error.code==='PRODUCT_NOT_FOUND'){sendApiError(res,ERROR_CODES.RESOURCE_NOT_FOUND);return;}
    next(error);
  }
}
