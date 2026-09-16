import { Request, Response } from "express";
import {
  createPromocodeService,
  getPromocodeService,
  updatePromocodeService,
  validatePromoCode
} from "../service/promocodes.service.js";
import { errorResponse } from "../../../types/response.js";
export async function validatePromoHandler(req: Request, resp: Response) {
  const { code, plan } = req.body;
  const result = await validatePromoCode(code, plan);
  if (!result.success) {
    const { error } = result;
    return resp
      .status(error.statusCode)
      .json(errorResponse(error.message, error.statusCode, error.code));
  }
  resp.status(200).json(result);
}
export async function patchPromocodeHandler(req: Request, resp: Response) {
  const id: string = req.params.id as string;
  const result = await updatePromocodeService(id, req.body);

  if (!result.success) {
    resp.status(result.error.statusCode).json(result);
  }
  resp.status(200).json(result);
}
export async function getPromocodeHandler(req: Request, resp: Response) {
  const result = await getPromocodeService();

  resp.status(200).json(result);
}
export async function postPromocodeHandler(req: Request, resp: Response) {
  const result = await createPromocodeService(req.body);

  if (!result.success) {
    resp.status(result.error.statusCode).json(result);
  }
  resp.status(201).json(result);
}
