import express, { Router, type NextFunction, type Response } from "express";
import jwt from "jsonwebtoken";
import { prisma } from "../../../config/database.js";
import { verifyPassword, generateAccessToken } from "../../../utils/token.js";
import {
  authenticateUser,
  requireTenant
} from "../../../middleware/validators/validateUser.js";
import { ERROR_CODES } from "../../../errors/error-codes.js";
import { sendApiError } from "../../../utils/http.js";
import type { AppRequest } from "../../../types/request.js";
import { validateBody } from "../../../middleware/validators/validateBody.js";
import {
  PortalError,
  invitationDetails,
  acceptInvite
} from "../../owner-portal/service/owner-write.service.js";
import { selectLoginMembership } from "../service/login-membership.js";
import * as authRepo from "../repo/auth.repo.js";
import {
  changePasswordSchema,
  emailOnlySchema,
  emailVerificationCodeSchema,
  emailVerificationTokenSchema,
  registerSchema
} from "../types/auth.dto.js";
import {
  changePasswordHandler,
  confirmEmailHandler,
  exchangeVerificationCodeHandler,
  meHandler,
  registerHandler,
  resendVerificationHandler,
  verificationPageHandler
} from "../controller/auth.controller.js";

const router = Router();
const failures = new Map<string, { count: number; expires: number }>();
const verificationRequests = new Map<
  string,
  { count: number; expires: number }
>();

function rateLimitVerificationRequests(
  req: AppRequest,
  res: Response,
  next: NextFunction
) {
  const key = req.ip || "unknown";
  const now = Date.now();
  const request = verificationRequests.get(key);
  if (request && request.expires > now && request.count >= 10) {
    return res
      .status(429)
      .json({ error: { code: "RATE_LIMITED", message: "Try again later" } });
  }

  if (request && request.expires > now) request.count += 1;
  else verificationRequests.set(key, { count: 1, expires: now + 15 * 60_000 });

  if (verificationRequests.size > 5000) {
    for (const [requestKey, value] of verificationRequests) {
      if (value.expires <= now) verificationRequests.delete(requestKey);
    }
  }
  next();
}

router.post("/login", async (req: AppRequest, res) => {
  const email =
    typeof req.body?.email === "string"
      ? req.body.email.trim().toLowerCase()
      : "";
  const password = req.body?.password;
  if (
    !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) ||
    email.length > 255 ||
    typeof password !== "string" ||
    password.length < 1 ||
    password.length > 1024
  ) {
    sendApiError(res, ERROR_CODES.INVALID_CREDENTIALS);
    return;
  }
  const key = `${req.ip || "unknown"}:${email}`;
  const now = Date.now();
  const failed = failures.get(key);
  if (failed && failed.expires > now && failed.count >= 10) {
    res
      .status(429)
      .json({ error: { code: "RATE_LIMITED", message: "Try again later" } });
    return;
  }
  try {
    const user = await authRepo.findUserByEmail(email);
    console.info("[login] user found:", Boolean(user));

    const passwordValid = user
      ? await verifyPassword(password, user.passwordHash)
      : false;
    console.info("[login] password valid:", passwordValid);

    // const memberships = await authRepo.findLoginMemberships(user.userId, email);
    // console.info("[login] active memberships:", memberships.length);

    if (!user || !passwordValid) {
      failures.set(key, {
        count: failed && failed.expires > now ? failed.count + 1 : 1,
        expires:
          failed && failed.expires > now ? failed.expires : now + 15 * 60_000
      });
      sendApiError(res, ERROR_CODES.INVALID_CREDENTIALS);
      return;
    }

    // Do not query workspace membership until the password has been verified.
    const memberships = await authRepo.findLoginMemberships(user.userId, email);
    if (!memberships.length) {
      failures.set(key, {
        count: failed && failed.expires > now ? failed.count + 1 : 1,
        expires:
          failed && failed.expires > now ? failed.expires : now + 15 * 60_000
      });
      sendApiError(res, ERROR_CODES.INVALID_CREDENTIALS);
      return;
    }
    failures.delete(key);
    const membership = selectLoginMembership(memberships);
    const session = await prisma.authSession.create({
      data: {
        userId: user.userId,
        tenantId: membership.tenantId,
        device: (req.headers["user-agent"] || "Browser").slice(0, 255),
        expiresAt: new Date(Date.now() + 3600_000)
      }
    });
    const accessToken = generateAccessToken({
      user_id: user.userId,
      id: user.userId,

      email: user.email,
      tenant_id: membership.tenantId,
      roleKey: membership.roleKey,
      sessionId: session.id,
      sessionVersion: user.sessionVersion
    });
    const decoded = jwt.decode(accessToken);
    if (
      decoded &&
      typeof decoded !== "string" &&
      typeof decoded.exp === "number"
    ) {
      await prisma.authSession.update({
        where: { id: session.id },
        data: { expiresAt: new Date(decoded.exp * 1000) }
      });
    }
    res.json({
      session: {
        accessToken,
        refreshToken: null,
        tenantId: membership.tenantId,
        roleKey: membership.roleKey,
        roles: [membership.roleKey],
        user: {
          id: user.userId,
          email: user.email,
          fullName: user.fullName,
          preferredLanguage: user.preferredLanguage,
          company: {
            id: membership.tenant.id,
            business_name: membership.tenant.businessName,
            business_type: membership.tenant.businessType,
            country_code: membership.tenant.countryCode,
            primary_currency: membership.tenant.primaryCurrency
          }
        }
      }
    });
  } catch (error) {
    console.error("Authentication failed:", error);
    sendApiError(res, ERROR_CODES.INTERNAL_SERVER_ERROR);
  }
});

router.post(
  "/register",
  rateLimitVerificationRequests,
  validateBody(registerSchema),
  registerHandler
);
router.post(
  "/verification/resend",
  rateLimitVerificationRequests,
  validateBody(emailOnlySchema),
  resendVerificationHandler
);
router.get("/verify-email", verificationPageHandler);
router.post(
  "/verify-email/confirm",
  express.urlencoded({ extended: false, limit: "1kb" }),
  validateBody(emailVerificationTokenSchema),
  confirmEmailHandler
);
router.post(
  "/verification/exchange",
  validateBody(emailVerificationCodeSchema),
  exchangeVerificationCodeHandler
);

router.get("/me", authenticateUser, requireTenant, meHandler);

router.post(
  "/change-password",
  authenticateUser,
  requireTenant,
  validateBody(changePasswordSchema),
  changePasswordHandler
);

router.get(
  "/session",
  authenticateUser,
  requireTenant,
  (req: AppRequest, res) => {
    res.json({
      userId: req.user!.user_id,
      tenantId: req.tenant_id,
      roleKey: req.tenantUser?.roleKey
    });
  }
);

router.post(
  "/logout",
  authenticateUser,
  requireTenant,
  async (req: AppRequest, res) => {
    if (req.user?.sessionId)
      await prisma.authSession.updateMany({
        where: {
          id: req.user.sessionId,
          userId: req.user.user_id
        },
        data: { revokedAt: new Date() }
      });
    res.json({ loggedOut: true });
  }
);

router.get("/invitations/:token", async (req: AppRequest, res) => {
  try {
    const token = String(req.params.token || "");
    if (token.length < 32 || token.length > 128)
      throw new PortalError("notFound");
    res.json(await invitationDetails(token));
  } catch (error) {
    if (error instanceof PortalError)
      res.status(404).json({ error: { code: "notFound" } });
    else throw error;
  }
});
router.post(
  "/invitations/:token/accept",
  authenticateUser,
  requireTenant,
  async (req: AppRequest, res) => {
    try {
      const token = String(req.params.token || "");
      if (token.length < 32 || token.length > 128)
        throw new PortalError("notFound");
      res.json(await acceptInvite(token, req.user?.user_id as string));
    } catch (error) {
      if (error instanceof PortalError)
        res
          .status(error.code === "forbidden" ? 403 : 409)
          .json({ error: { code: error.code, message: error.message } });
      else throw error;
    }
  }
);

export default router;
