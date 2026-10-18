import z from "zod";

/*
 * Tenant roles
 *
 * These belong to normal customer/company memberships.
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
 * Platform roles
 *
 * These belong to the CEOPRO platform administration team.
 */
export const PLATFORM_ROLES = ["owner", "admin"] as const;

export const platformRoleSchema = z.enum(PLATFORM_ROLES);

export type PlatformRole = (typeof PLATFORM_ROLES)[number];

/*
 * Platform owner is unique/protected.
 *
 * New platform-team invitations may only create admins.
 */
export const INVITABLE_PLATFORM_ROLES = ["admin"] as const;

export type InvitablePlatformRole = (typeof INVITABLE_PLATFORM_ROLES)[number];

export function isInvitablePlatformRole(
  value: string
): value is InvitablePlatformRole {
  return (INVITABLE_PLATFORM_ROLES as readonly string[]).includes(value);
}

/*
 * Normal tenant members that may be invited.
 *
 * "owner" is intentionally excluded because ownership should not be
 * created through the normal invitation flow.
 */
export const INVITABLE_TENANT_ROLES = [
  "admin",
  "manager",
  "accountant",
  "staff"
] as const;

export type InvitableTenantRole = (typeof INVITABLE_TENANT_ROLES)[number];

export function isInvitableTenantRole(
  value: string
): value is InvitableTenantRole {
  return (INVITABLE_TENANT_ROLES as readonly string[]).includes(value);
}
