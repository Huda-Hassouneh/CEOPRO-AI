import type { Response } from "express";
import type { AppRequest } from "../../../types/request.js";
import { successResponse } from "../../../types/response.js";
import { sendApiError } from "../../../utils/http.js";
import type { ChangePasswordInput, RegisterInput } from "../types/auth.dto.js";
import * as authService from "../service/auth.service.js";

export async function registerHandler(req: AppRequest, res: Response) {
  const result = await authService.register(req.body as RegisterInput);
  if (!result.success) {
    return sendApiError(res, result.code);
  }
  return res.status(202).json({ message: result.message, data: result.data });
}

export async function resendVerificationHandler(req: AppRequest, res: Response) {
  const result = await authService.resendVerification(req.body.email);
  if (!result.success) return sendApiError(res, result.code);
  return res.status(202).json({ message: result.message, data: result.data });
}

export function verificationPageHandler(req: AppRequest, res: Response) {
  const token = typeof req.query.token === "string" ? req.query.token : "";
  if (!/^[a-f0-9]{64}$/i.test(token)) {
    return res.status(400).type("text/plain").send("Invalid or expired verification link.");
  }

  // A GET only displays a confirmation form. Mail security scanners often
  // prefetch links, so account creation happens only after the user submits it.
  return res
    .set("Cache-Control", "no-store")
    .set("Referrer-Policy", "no-referrer")
    .type("html")
    .send(`<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Verify CEO PRO email</title><body><main><h1>Verify your email</h1><p>Confirm this email address to create your CEO PRO account.</p><form method="post" action="/auth/verify-email/confirm"><input type="hidden" name="token" value="${token}"><button type="submit">Verify email</button></form></main></body></html>`);
}

export async function confirmEmailHandler(req: AppRequest, res: Response) {
  const result = await authService.confirmEmail(req.body.token);
  if (!result.success) {
    return res
      .status(400)
      .type("text/html")
      .send("<!doctype html><html><meta charset=\"utf-8\"><title>Verification failed</title><body><h1>Verification link expired or invalid</h1><p>Return to CEO PRO and request another verification email.</p></body></html>");
  }

  const frontendOrigin =
    process.env.FRONTEND_URL?.trim() ||
    process.env.CORS_ORIGINS?.split(",")[0]?.trim() ||
    "http://localhost:5173";
  const destination = new URL("/verify-email", frontendOrigin);
  destination.searchParams.set("code", result.data.code);
  return res.redirect(303, destination.toString());
}

export async function exchangeVerificationCodeHandler(
  req: AppRequest,
  res: Response
) {
  const result = await authService.exchangeVerificationCode(req.body.code);
  if (!result.success) return sendApiError(res, result.code);
  return res.json(result.data);
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
