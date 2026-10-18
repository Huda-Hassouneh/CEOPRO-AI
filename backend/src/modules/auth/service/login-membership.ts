type LoginMembership = {
  roleKey: string;
  tenant: { businessType: string | null };
};

/**
 * Select the workspace that should back a newly issued login token.
 * Platform owners land in the platform workspace. Other users with a
 * customer membership land in that customer workspace, even if they also
 * have a platform membership. Platform-only users retain platform access.
 */
export function selectLoginMembership<T extends LoginMembership>(
  memberships: readonly T[]
): T {
  const membership =
    memberships.find(
      (item) =>
        item.roleKey === "owner" && item.tenant.businessType === "platform"
    ) ??
    memberships.find((item) => item.tenant.businessType !== "platform") ??
    memberships.find((item) => item.tenant.businessType === "platform") ??
    memberships[0];

  if (!membership) {
    throw new Error("Cannot select a login workspace without a membership.");
  }

  return membership;
}
