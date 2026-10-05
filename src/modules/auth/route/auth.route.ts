import { Router } from "express";
import { prisma } from "../../../config/database.js";
import { verifyPassword } from "../../../utils/token.js";
import { validateBody } from "../../../validators/validateBody.js";
import {
  authenticateUser,
  requireTenant
} from "../../../validators/validateUser.js";
import { ERROR_CODES } from "../../../errors/error-codes.js";
import { sendApiError } from "../../../utils/http.js";
import type { AppRequest } from "../../../types/request.js";
import {
  PortalError,
  invitationDetails,
  acceptInvite
} from "../../owner-portal/service/owner-write.service.js";
import { issueSession } from "../service/auth.service.js";
import { changePasswordSchema, registerSchema } from "../types/auth.dto.js";
import {
  changePasswordHandler,
  meHandler,
  registerHandler
} from "../controller/auth.controller.js";

const router = Router();
const failures = new Map<string, { count: number; expires: number }>();

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
    const user = await prisma.user.findFirst({
      where: { email: { equals: email, mode: "insensitive" } },
      include: {
        tenantUsers: {
          where: {
            removedAt: null,
            platformStatus: "active",
            tenant: { deletedAt: null, platformStatus: "active" }
          },
          include: { tenant: true },
          orderBy: { joinedAt: "asc" }
        }
      }
    });
    if (
      !user ||
      !user.tenantUsers.length ||
      !(await verifyPassword(password, user.passwordHash))
    ) {
      failures.set(key, {
        count: failed && failed.expires > now ? failed.count + 1 : 1,
        expires:
          failed && failed.expires > now ? failed.expires : now + 15 * 60_000
      });
      sendApiError(res, ERROR_CODES.INVALID_CREDENTIALS);
      return;
    }
    failures.delete(key);
    // An accepted owner invitation should lead to the platform workspace.
    const membership =
      user.tenantUsers.find((m) => m.tenant.businessType === "platform") ||
      user.tenantUsers[0];
    res.json(
      await issueSession(
        user,
        membership,
        req.headers["user-agent"] || "Browser"
      )
    );
  } catch (error) {
    console.error("Authentication failed:", error);
    sendApiError(res, ERROR_CODES.INTERNAL_SERVER_ERROR);
  }
});

router.post("/register", validateBody(registerSchema), registerHandler);

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
      userId: req.user!.id,
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
          userId: req.user.id
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
      res.json(await acceptInvite(token, req.user!.id));
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
