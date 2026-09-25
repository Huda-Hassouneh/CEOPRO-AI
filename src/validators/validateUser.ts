import type { NextFunction, Response } from "express";
import jwt from "jsonwebtoken";
import { ERROR_CODES } from "../errors/error-codes.js";
import { getActiveTenantUser } from "../modules/subscription/repo/user-tenant.repo.js";
import type { AppRequest, AuthenticatedUser } from "../types/request.js";
import { sendApiError } from "../utils/http.js";

export function authenticateUser(
  req: AppRequest,
  res: Response,
  next: NextFunction
): void {
  const authHeader = req.headers.authorization;
  if (!authHeader || !/^Bearer\s+\S+$/i.test(authHeader)) {
    sendApiError(res, ERROR_CODES.INVALID_AUTH_HEADER);
    return;
  }

  const secret = process.env.JWT_SECRET?.trim();
  if (!secret) {
    console.error("JWT_SECRET is not configured");
    sendApiError(res, ERROR_CODES.INTERNAL_SERVER_ERROR);
    return;
  }

  try {
    const decoded = jwt.verify(authHeader.replace(/^Bearer\s+/i, ""), secret, {
      algorithms: ["HS256"]
    });

    if (
      typeof decoded === "string" ||
      !decoded ||
      typeof decoded.id !== "string" ||
      typeof decoded.email !== "string"
    ) {
      sendApiError(res, ERROR_CODES.INVALID_TOKEN);
      return;
    }

    req.user = decoded as AuthenticatedUser;

    next();
  } catch (error) {
    sendApiError(
      res,
      error instanceof jwt.TokenExpiredError
        ? ERROR_CODES.TOKEN_EXPIRED
        : ERROR_CODES.INVALID_TOKEN
    );
  }
}

export async function requireTenant(
  req: AppRequest,
  res: Response,
  next: NextFunction
): Promise<void> {
  const tenantId = req.user?.tenant_id;
  const userId = req.user?.id;

  if (!tenantId || !userId) {
    sendApiError(res, ERROR_CODES.TENANT_ACCESS_DENIED);
    return;
  }

  try {
    const tenantUser = await getActiveTenantUser(tenantId, userId);
    if (!tenantUser) {
      sendApiError(res, ERROR_CODES.TENANT_ACCESS_DENIED);
      return;
    }

    req.tenant_id = tenantId;
    req.tenantUser = tenantUser;

    next();
  } catch (error) {
    console.error("Tenant membership check failed:", error);
    sendApiError(res, ERROR_CODES.INTERNAL_SERVER_ERROR);
  }
}

export function requirePermission(requiredAction: string) {
  return async (
    req: AppRequest,
    res: Response,
    next: NextFunction
  ): Promise<void> => {
    const userId = req.user?.id;
    const tenantId = req.tenant_id;

    if (!userId || !tenantId) {
      sendApiError(res, ERROR_CODES.TENANT_ACCESS_DENIED);
      return;
    }

    try {
      const tenantUser =
        req.tenantUser ?? (await getActiveTenantUser(tenantId, userId));
      const permissions = tenantUser?.role?.permissions;

      if (
        !permissions ||
        typeof permissions !== "object" ||
        Array.isArray(permissions)
      ) {
        sendApiError(res, ERROR_CODES.FORBIDDEN);
        return;
      }

      const rolePermissions = permissions as Record<string, unknown>;
      const allowed =
        rolePermissions.all === true ||
        rolePermissions[requiredAction] === true;

      if (!allowed) {
        sendApiError(res, ERROR_CODES.FORBIDDEN);
        return;
      }

      next();
    } catch (error) {
      console.error(`Permission check failed for [${requiredAction}]:`, error);
      sendApiError(res, ERROR_CODES.INTERNAL_SERVER_ERROR);
    }
  };
}
