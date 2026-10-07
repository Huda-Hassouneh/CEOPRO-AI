import type { Response, NextFunction } from "express";
import { z } from "zod";
import type { AppRequest } from "../../../types/request.js";
import { requirePlatformPermission } from "../../../middleware/validators/validatePlatformUser.js";
import {
  PortalError,
  type Actor,
  updateCompany,
  updateCustomerUser,
  createInvite,
  updateTeam,
  updateSettings,
  updateProfile,
  changePassword,
  sessions,
  revokeSession
} from "../service/owner-write.service.js";
import * as read from "../service/owner-read.service.js";

/*
 * Normal tenant/company membership roles.
 */
export const TENANT_ROLES = [
  "owner",
  "admin",
  "manager",
  "accountant",
  "staff"
] as const;

export const tenantRoleSchema = z.enum(TENANT_ROLES);

export type TenantRole = (typeof TENANT_ROLES)[number];

/*
 * CEOPRO platform administration roles.
 */
export const PLATFORM_ROLES = ["owner", "admin"] as const;

export const platformRoleSchema = z.enum(PLATFORM_ROLES);

export type PlatformRole = (typeof PLATFORM_ROLES)[number];

/*
 * The platform owner is protected and must not be created
 * through the normal admin-team invitation flow.
 */
export const INVITABLE_PLATFORM_ROLES = ["admin"] as const;

export const invitablePlatformRoleSchema = z.enum(INVITABLE_PLATFORM_ROLES);

export type InvitablePlatformRole = (typeof INVITABLE_PLATFORM_ROLES)[number];

export function isInvitablePlatformRole(
  value: string
): value is InvitablePlatformRole {
  return (INVITABLE_PLATFORM_ROLES as readonly string[]).includes(value);
}

export const permission = requirePlatformPermission;
const uuid = z.uuid();
const listSchema = z
  .object({
    q: z.string().max(150).optional(),
    page: z.coerce.number().int().min(1).max(100000).optional(),
    pageSize: z.coerce.number().int().min(1).max(50).optional(),
    sort: z.string().max(40).optional(),
    direction: z.enum(["asc", "desc"]).optional(),
    planId: uuid.optional(),
    status: z.string().max(30).optional(),
    subscriptionStatus: z.string().max(30).optional(),
    country: z.string().max(2).optional(),
    role: z.string().max(50).optional(),
    companyId: uuid.optional(),
    actor: z.string().max(150).optional(),
    action: z.string().max(50).optional(),
    targetType: z.string().max(100).optional(),
    from: z.iso.date().optional(),
    to: z.iso.date().optional()
  })
  .strip();

function actor(req: AppRequest): Actor {
  return {
    tenantId: req.tenant_id!,
    userId: req.user!.id,
    name: req.user!.email,
    role: req.tenantUser!.roleKey
  };
}
function params(req: AppRequest) {
  const parsed = listSchema.safeParse(req.query);
  if (!parsed.success) throw new PortalError("invalid");
  return parsed.data;
}
function id(req: AppRequest) {
  const parsed = uuid.safeParse(req.params.id);
  if (!parsed.success) throw new PortalError("invalid");
  return parsed.data;
}
function body<T>(req: AppRequest, schema: z.ZodType<T>): T {
  const parsed = schema.safeParse(req.body);
  if (!parsed.success) throw new PortalError("invalid");
  return parsed.data;
}
type Handler = (req: AppRequest) => Promise<unknown>;
export const handle =
  (fn: Handler) =>
  async (req: AppRequest, res: Response, next: NextFunction) => {
    try {
      const result = await fn(req);
      if (result === null) throw new PortalError("notFound");
      res.json(result);
    } catch (error) {
      if (error instanceof PortalError) {
        const status = {
          invalid: 400,
          notFound: 404,
          duplicate: 409,
          conflict: 409,
          lastAdmin: 409,
          forbidden: 403,
          accountRequired: 422
        }[error.code];
        res
          .status(status)
          .json({ error: { code: error.code, message: error.message } });
        return;
      }
      next(error);
    }
  };
export const readOverview = handle((req) => read.overview(req.tenant_id!));
export const readCompanies = handle((req) =>
  read.companies(req.tenant_id!, params(req))
);
export const readCompany = handle((req) =>
  read.companyDetail(req.tenant_id!, id(req))
);
export const readUsers = handle((req) =>
  read.users(req.tenant_id!, params(req))
);
export const readUser = handle((req) =>
  read.userDetail(req.tenant_id!, id(req))
);
export const readTeam = handle((req) => read.team(req.tenant_id!, params(req)));
export const readAudit = handle((req) =>
  read.auditLogs(req.tenant_id!, params(req))
);
export const readSettings = handle((req) => read.settings(req.tenant_id!));

export const companyMetadata = handle((req) =>
  updateCompany(
    actor(req),
    id(req),
    "metadata",
    body(req, z.object({ notes: z.string().max(2000) }).strict())
  )
);
export const companyStatus = handle((req) =>
  updateCompany(
    actor(req),
    id(req),
    "status",
    body(req, z.object({ status: z.enum(["active", "suspended"]) }).strict())
  )
);
export const userStatus = handle((req) =>
  updateCustomerUser(
    actor(req),
    id(req),
    body(req, z.object({ status: z.enum(["active", "suspended"]) }).strict())
      .status
  )
);
export const teamInvite = handle((req) => {
  const input = body(
    req,
    z
      .object({
        email: z.email().max(255),
        role: invitablePlatformRoleSchema
      })
      .strict()
  );

  return createInvite(actor(req), input.email, input.role);
});
export const teamRole = handle((req) =>
  updateTeam(
    actor(req),
    id(req),
    "role",
    body(
      req,
      z
        .object({
          role: platformRoleSchema
        })
        .strict()
    )
  )
);
export const teamStatus = handle((req) =>
  updateTeam(
    actor(req),
    id(req),
    "status",
    body(req, z.object({ status: z.enum(["active", "inactive"]) }).strict())
  )
);
export const teamRemove = handle((req) =>
  updateTeam(actor(req), id(req), "remove", {})
);
export const teamResend = handle((req) =>
  updateTeam(actor(req), id(req), "resend", {})
);
export const teamCancel = handle((req) =>
  updateTeam(actor(req), id(req), "cancel", {})
);
export const settingsUpdate = handle((req) => {
  const input = body(
    req,
    z
      .object({
        name: z.string().trim().min(1).max(100),
        supportEmail: z.email().max(255),
        language: z.enum(["en", "ar"]),
        currency: z.string().max(3)
      })
      .strict()
  );
  return read.settings(req.tenant_id!).then((current) => {
    if (!current || input.currency !== current.currency)
      throw new PortalError("invalid");
    return updateSettings(actor(req), input);
  });
});
export const accountProfile = handle((req) => {
  const input = body(
    req,
    z
      .object({
        name: z.string().trim().min(1).max(150),
        language: z.enum(["en", "ar"])
      })
      .strict()
  );
  return updateProfile(actor(req), input.name, input.language);
});
export const accountPassword = handle((req) => {
  const input = body(
    req,
    z
      .object({
        currentPassword: z.string().min(1).max(1024),
        newPassword: z.string().min(12).max(1024)
      })
      .strict()
  );
  return changePassword(actor(req), input.currentPassword, input.newPassword);
});
export const accountSessions = handle((req) =>
  sessions(actor(req), req.user?.sessionId)
);
export const accountRevoke = handle((req) =>
  revokeSession(
    actor(req),
    req.user?.sessionId,
    body(req, z.object({ id: uuid }).strict()).id
  )
);
export const accountRevokeOthers = handle((req) =>
  revokeSession(actor(req), req.user?.sessionId)
);
