import { NextFunction, Response } from "express";
import { ERROR_CODES } from "../errors/error-codes.js";
import { ERROR_DEFINITIONS } from "../errors/error-defentions.js";
import { errorResponse } from "../types/response.js";
import { getActiveTenantUser } from "../modules/subscription/repo/user-tenant.repo.js";
import jwt from "jsonwebtoken";

// Middleware to authenticate users by validating their JWT
export const authenticateUser = (
  req: any,
  res: Response,
  next: NextFunction
): void => {
  const authHeader = req.headers.authorization;

  // 1. Ensure the Authorization header exists and uses the Bearer scheme
  if (!authHeader || !authHeader.startsWith("Bearer ")) {
    const errDef = ERROR_DEFINITIONS[ERROR_CODES.INVALID_AUTH_HEADER];
    res
      .status(errDef.statusCode)
      .json(
        errorResponse(
          errDef.message,
          errDef.statusCode,
          ERROR_CODES.INVALID_AUTH_HEADER,
          "Unauthorized. Missing or invalid Bearer token."
        )
      );
    return;
  }

  // 2. Extract the raw token string
  const token = authHeader.split(" ")[1];
  const secret = process.env.JWT_SECRET || "";
  // console.log(jwt.verify(token, secret));

  try {
    // 3. Verify the token signature and expiration
    const decoded = jwt.verify(token, secret);

    // 4. Attach the decoded payload to the request object for downstream middlewares
    req.user = decoded;
    next();
  } catch (error) {
    const errDef = ERROR_DEFINITIONS[ERROR_CODES.INVALID_TOKEN];
    res
      .status(errDef.statusCode)
      .json(
        errorResponse(
          errDef.message,
          errDef.statusCode,
          ERROR_CODES.INVALID_TOKEN,
          "Forbidden. Invalid or expired token."
        )
      );
    return;
  }
};

// Middleware to verify if a user has a specific permission within their current tenant
// Note: Must be executed after requireTenant middleware
export const requirePermission = (requiredAction: string) => {
  return async (req: any, res: Response, next: NextFunction): Promise<void> => {
    try {
      const userId = req.user?.id;
      const tenantId = req.tenant_id;

      // 1. Validate that the request has the necessary context
      if (!userId || !tenantId) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.INVALID_REQUEST];
        res
          .status(errDef.statusCode)
          .json(
            errorResponse(
              errDef.message,
              errDef.statusCode,
              ERROR_CODES.INVALID_REQUEST,
              "User or Tenant context is missing."
            )
          );
        return;
      }

      // 2. Fetch the user's active role mapping for this specific workspace/tenant
      const tenantUser = await getActiveTenantUser(tenantId, userId);
      if (!tenantUser || !tenantUser.role) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.FORBIDDEN];
        res
          .status(errDef.statusCode)
          .json(
            errorResponse(
              errDef.message,
              errDef.statusCode,
              ERROR_CODES.FORBIDDEN,
              "You do not have an active role in this workspace."
            )
          );
        return;
      }

      // 3. Evaluate the permissions JSON object attached to the user's role
      const rolePermissions = tenantUser.role.permissions as Record<
        string,
        boolean
      >;

      // Grant access if the specific action is true, or if the role has the "all" master override
      const hasPermission =
        rolePermissions["all"] === true ||
        rolePermissions[requiredAction] === true;

      if (!hasPermission) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.FORBIDDEN];
        res
          .status(errDef.statusCode)
          .json(
            errorResponse(
              errDef.message,
              errDef.statusCode,
              ERROR_CODES.FORBIDDEN,
              `Forbidden: You lack the '${requiredAction}' permission in this workspace.`
            )
          );
        return;
      }

      // User is authorized, proceed to the next middleware or controller
      next();
    } catch (error) {
      console.error(`Permission Check Error for [${requiredAction}]:`, error);
      const errDef = ERROR_DEFINITIONS[ERROR_CODES.INTERNAL_SERVER_ERROR];
      res
        .status(errDef.statusCode)
        .json(
          errorResponse(
            errDef.message,
            errDef.statusCode,
            ERROR_CODES.INTERNAL_SERVER_ERROR,
            "Internal server error verifying permissions."
          )
        );
      return;
    }
  };
};

// Middleware to ensure the authenticated user is accessing the API within a tenant context.
// Note: Must be executed after authenticateUser middleware so req.user is populated.
export const requireTenant = (
  req: any,
  res: Response,
  next: NextFunction
): void => {
  // 1. Extract the user payload that was attached by the authenticateUser middleware
  const userPayload = req.user as any;

  // 2. Attempt to extract the tenant ID directly from the decoded JWT payload
  const tenantId = userPayload?.tenant_id;

  // 3. Reject the request if the token does not contain a tenant context
  if (!tenantId) {
    const errDef = ERROR_DEFINITIONS[ERROR_CODES.INVALID_REQUEST];
    res
      .status(errDef.statusCode)
      .json(
        errorResponse(
          errDef.message,
          errDef.statusCode,
          ERROR_CODES.INVALID_REQUEST,
          "Bad Request. Tenant context is missing."
        )
      );
    return;
  }

  // 4. Attach the tenant ID directly to the request object for downstream middlewares and controllers
  req.tenant_id = tenantId;

  // Proceed to the next middleware or controller
  next();
};
