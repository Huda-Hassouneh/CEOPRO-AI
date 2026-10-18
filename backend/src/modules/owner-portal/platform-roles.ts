export const INVITABLE_PLATFORM_ROLES = [
  "admin",
  "manager",
  "accountant",
  "staff"
] as const;

export type InvitablePlatformRole = (typeof INVITABLE_PLATFORM_ROLES)[number];

export function isInvitablePlatformRole(
  value: string
): value is InvitablePlatformRole {
  return (INVITABLE_PLATFORM_ROLES as readonly string[]).includes(value);
}
