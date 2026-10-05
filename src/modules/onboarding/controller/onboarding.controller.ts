import type { Response } from "express";
import type { AppRequest } from "../../../types/request.js";
import { successResponse } from "../../../types/response.js";
import { sendApiError } from "../../../utils/http.js";
import type {
  CompleteOnboardingInput,
  GoalsInput,
  PlanInput,
  ProfileInput,
  RegionalPreferencesInput
} from "../types/onboarding.dto.js";
import * as service from "../service/onboarding.service.js";

function respond(
  res: Response,
  result: Awaited<ReturnType<typeof service.getState>>
) {
  if (!result.success) return sendApiError(res, result.code);
  return res.json(successResponse(result.data, result.message!));
}

export async function getStateHandler(req: AppRequest, res: Response) {
  return respond(res, await service.getState(req.tenant_id!));
}

export async function saveRegionHandler(req: AppRequest, res: Response) {
  return respond(
    res,
    await service.saveRegion(
      req.tenant_id!,
      req.user!.id,
      req.body as RegionalPreferencesInput
    )
  );
}

export async function saveProfileHandler(req: AppRequest, res: Response) {
  return respond(
    res,
    await service.saveProfile(req.tenant_id!, req.body as ProfileInput)
  );
}

export async function saveGoalsHandler(req: AppRequest, res: Response) {
  return respond(
    res,
    await service.saveGoals(req.tenant_id!, req.body as GoalsInput)
  );
}

export async function savePlanHandler(req: AppRequest, res: Response) {
  return respond(
    res,
    await service.savePlan(req.tenant_id!, req.body as PlanInput)
  );
}

export async function completeHandler(req: AppRequest, res: Response) {
  return respond(
    res,
    await service.complete(req.tenant_id!, req.body as CompleteOnboardingInput)
  );
}
