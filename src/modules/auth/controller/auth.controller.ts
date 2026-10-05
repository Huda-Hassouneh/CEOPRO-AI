import type { Response } from "express";
import type { AppRequest } from "../../../types/request.js";
import { successResponse } from "../../../types/response.js";
import { sendApiError } from "../../../utils/http.js";
import type { ChangePasswordInput, RegisterInput } from "../types/auth.dto.js";
import * as authService from "../service/auth.service.js";

export async function registerHandler(req: AppRequest, res: Response) {
  const result = await authService.register(
    req.body as RegisterInput,
    req.headers["user-agent"] || "Browser"
  );
  if (!result.success) {
    return sendApiError(res, result.code);
  }

  // Same body as POST /auth/login so clients can treat both alike.
  return res.status(201).json(result.data);
}

export async function meHandler(req: AppRequest, res: Response) {
  const result = await authService.me(req.user!.id, req.tenant_id!);
  if (!result.success) {
    return sendApiError(res, result.code);
  }

  return res.json(
    successResponse(result.data, "Current user retrieved successfully")
  );
}

export async function changePasswordHandler(req: AppRequest, res: Response) {
  const result = await authService.changePassword(
    req.user!.id,
    req.body as ChangePasswordInput,
    req.user!.sessionId
  );
  if (!result.success) {
    return sendApiError(res, result.code);
  }

  return res.json(successResponse(result.data, result.message!));
}
