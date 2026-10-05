import jwt from "jsonwebtoken";
import { ERROR_CODES } from "../../../errors/error-codes.js";
import type { Company, TenantUser, User } from "../../../generated/prisma/client.js";
import type { ServiceResult } from "../../../types/service.js";
import {
  generateAccessToken,
  hashPassword,
  verifyPassword
} from "../../../utils/token.js";
import type { ChangePasswordInput, RegisterInput } from "../types/auth.dto.js";
import * as repo from "../repo/auth.repo.js";

type MembershipWithTenant = TenantUser & { tenant: Company };

function isUniqueViolation(error: unknown): boolean {
  const code = (error as { code?: string })?.code;
  return code === "P2002" || code === "23505";
}

/**
 * Persists an auth session and returns the login response body. Shared by
 * login and register so both hand the client the same session contract.
 */
export async function issueSession(
  user: User,
  membership: MembershipWithTenant,
  device: string
) {
  const session = await repo.createSession({
    userId: user.userId,
    tenantId: membership.tenantId,
    device: device.slice(0, 255),
    expiresAt: new Date(Date.now() + 3600_000)
  });
  const accessToken = generateAccessToken({
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
    await repo.updateSessionExpiry(session.id, new Date(decoded.exp * 1000));
  }

  return {
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
  };
}

export async function register(
  input: RegisterInput,
  device: string
): Promise<ServiceResult<Awaited<ReturnType<typeof issueSession>>>> {
  if (await repo.findUserByEmail(input.email)) {
    return { success: false, code: ERROR_CODES.USER_ALREADY_EXISTS };
  }

  let created;
  try {
    created = await repo.createUserWithCompany({
      ...input,
      passwordHash: await hashPassword(input.password)
    });
  } catch (error) {
    if (isUniqueViolation(error)) {
      return { success: false, code: ERROR_CODES.USER_ALREADY_EXISTS };
    }
    throw error;
  }

  return {
    success: true,
    data: await issueSession(created.user, created.membership, device),
    message: "Account created successfully"
  };
}

export async function me(userId: string, tenantId: string) {
  const user = await repo.findUserById(userId);
  if (!user) {
    return { success: false as const, code: ERROR_CODES.USER_NOT_FOUND };
  }

  const membership = await repo.findMembership(userId, tenantId);
  if (!membership) {
    return { success: false as const, code: ERROR_CODES.TENANT_ACCESS_DENIED };
  }

  const memberships = await repo.findActiveMemberships(userId);

  return {
    success: true as const,
    data: {
      user: {
        id: user.userId,
        email: user.email,
        fullName: user.fullName,
        preferredLanguage: user.preferredLanguage,
        createdAt: user.createdAt
      },
      membership: {
        tenantId: membership.tenantId,
        roleKey: membership.roleKey,
        roleName: membership.role.roleName,
        businessName: membership.tenant.businessName
      },
      memberships: memberships.map((m) => ({
        tenantId: m.tenantId,
        roleKey: m.roleKey,
        businessName: m.tenant.businessName
      }))
    }
  };
}

export async function changePassword(
  userId: string,
  input: ChangePasswordInput,
  currentSessionId?: string
): Promise<ServiceResult<{ userId: string }>> {
  const user = await repo.findUserById(userId);
  if (!user) {
    return { success: false, code: ERROR_CODES.USER_NOT_FOUND };
  }

  if (!(await verifyPassword(input.currentPassword, user.passwordHash))) {
    return { success: false, code: ERROR_CODES.INVALID_CREDENTIALS };
  }

  await repo.updatePassword(
    userId,
    await hashPassword(input.newPassword),
    currentSessionId
  );

  return {
    success: true,
    data: { userId },
    message: "Password changed successfully"
  };
}
