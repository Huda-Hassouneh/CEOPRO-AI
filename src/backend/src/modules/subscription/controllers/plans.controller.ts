import { Request, Response } from "express";
import {
  changePlanService,
  createPlansService,
  getPlansService,
  updatePlansService
} from "../service/plans.service.js";
import { errorResponse } from "../../../types/response.js";

export async function getPlansHndler(req: Request, resp: Response) {
  const result = await getPlansService();

  resp.status(200).json(result);
}
export async function postPlanHandler(req: Request, resp: Response) {
  console.log(req.body);
  const result = await createPlansService(req.body);

  if (!result.success) {
    resp.status(result.error.statusCode).json(result);
  }
  resp.status(201).json(result);
}
export async function changePlanHandler(req: Request, resp: Response) {
  const result = await changePlanService(req.body.planId);

  // if (!result.success) {
  //   resp.status(result.error.statusCode).json(result);
  // }
  // resp.status(201).json(result);
  if (!result.success) {
    resp.status(result.error.statusCode).json(result);
  }
  resp.status(201).json(result);
}

export async function patchPlanHandler(req: Request, resp: Response) {
  const id: string = req.params.id as string;
  const result = await updatePlansService(id, req.body);

  if (!result.success) {
    resp.status(result.error.statusCode).json(result);
  }
  resp.status(200).json(result);
}
