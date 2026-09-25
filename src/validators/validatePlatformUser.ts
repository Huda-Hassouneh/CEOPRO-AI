import type { NextFunction, Response } from "express";
import { ERROR_CODES } from "../errors/error-codes.js";
import { getActiveTenantUser } from "../modules/subscription/repo/user-tenant.repo.js";
import type { AppRequest } from "../types/request.js";
import { sendApiError } from "../utils/http.js";

const PLATFORM_OWNER_ROLE_KEY = "owner";

async function ensureTenantUser(req: AppRequest) {
  if (req.tenantUser) return req.tenantUser;

  const tenantId = req.user?.tenant_id;
  const userId = req.user?.id;
  if (!tenantId || !userId) return null;

  const tenantUser = await getActiveTenantUser(tenantId, userId);
  if (!tenantUser) return null;

  req.tenant_id = tenantId;
  req.tenantUser = tenantUser;
  return tenantUser;
}

function getRolePermissions(req: AppRequest): Record<string, unknown> | null {
  const permissions = req.tenantUser?.role?.permissions;
  if (
    !permissions ||
    typeof permissions !== "object" ||
    Array.isArray(permissions)
  ) {
    return null;
  }
  return permissions as Record<string, unknown>;
}

/**
 * Platform administration uses the normal TenantUser membership. There is no
 * separate platform_role/SUPER_ADMIN identity model. The active membership
 * loaded from the database is authoritative; the JWT roleKey is not trusted
 * as the authorization decision by itself.
 */
export function getPlatformRole(req: AppRequest): string | null {
  return req.tenantUser?.roleKey === PLATFORM_OWNER_ROLE_KEY
    ? req.tenantUser.roleKey
    : null;
}

export async function requirePlatformRole(
  req: AppRequest,
  res: Response,
  next: NextFunction
): Promise<void> {
  try {
    console.log("owner");

    await ensureTenantUser(req);
    if (!getPlatformRole(req)) {
      sendApiError(res, ERROR_CODES.FORBIDDEN, {
        publicMessage: "Platform owner access is required."
      });
      return;
    }
    next();
  } catch (error) {
    console.error("Platform owner membership check failed:", error);
    sendApiError(res, ERROR_CODES.INTERNAL_SERVER_ERROR);
  }
}

export function requirePlatformPermission(permission: string) {
  return async (
    req: AppRequest,
    res: Response,
    next: NextFunction
  ): Promise<void> => {
    try {
      await ensureTenantUser(req);
      if (!getPlatformRole(req)) {
        sendApiError(res, ERROR_CODES.FORBIDDEN, {
          publicMessage: "Platform owner access is required."
        });
        return;
      }

      const permissions = getRolePermissions(req);
      const allowed =
        permissions?.all === true || permissions?.[permission] === true;

      if (!allowed) {
        sendApiError(res, ERROR_CODES.FORBIDDEN, {
          publicMessage:
            "You do not have permission to perform this platform action."
        });
        return;
      }
      next();
    } catch (error) {
      console.error(
        `Platform permission check failed for [${permission}]:`,
        error
      );
      sendApiError(res, ERROR_CODES.INTERNAL_SERVER_ERROR);
    }
  };
}

export function platformCan(req: AppRequest, permission: string): boolean {
  if (!getPlatformRole(req)) return false;
  const permissions = getRolePermissions(req);
  return permissions?.all === true || permissions?.[permission] === true;
}
