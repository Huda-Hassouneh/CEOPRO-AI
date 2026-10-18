import { createHash, randomBytes } from "node:crypto";
import { hashPassword, verifyPassword } from "../../../utils/token.js";
import {
  ownerDb,
  auditWrite,
  companyById,
  userById
} from "../repo/owner.repo.js";
import {
  InvitablePlatformRole,
  isInvitablePlatformRole
} from "../types/platform-roles.js";

export class PortalError extends Error {
  constructor(
    public code:
      | "invalid"
      | "notFound"
      | "duplicate"
      | "conflict"
      | "lastAdmin"
      | "forbidden"
      | "accountRequired",
    message: string = code
  ) {
    super(message);
  }
}
export type Actor = {
  tenantId: string;
  userId: string;
  name: string;
  role: string;
};
const tokenHash = (value: string) =>
  createHash("sha256").update(value).digest("hex");
const changes = (key: string, before: unknown, after: unknown) => [
  { key, before, after }
];

export async function updateCompany(
  actor: Actor,
  id: string,
  action: "metadata" | "status",
  input: { notes?: string; status?: "active" | "suspended" }
) {
  if (id === actor.tenantId) throw new PortalError("forbidden");
  return ownerDb.$transaction(async (tx) => {
    const row = await tx.company.findFirst({ where: { id, deletedAt: null } });
    if (!row) throw new PortalError("notFound");
    if (row.businessType === "platform") throw new PortalError("forbidden");
    const next =
      action === "metadata"
        ? { platformNotes: input.notes?.trim() || null }
        : { platformStatus: input.status! };
    const updated = await tx.company.update({ where: { id }, data: next });
    const field = action === "metadata" ? "notes" : "status";
    await auditWrite(tx, actor, {
      action: action === "metadata" ? "metadataUpdated" : "statusChanged",
      domain: "companies",
      target: row.businessName,
      companyId: id,
      changes: changes(
        field,
        action === "metadata" ? row.platformNotes : row.platformStatus,
        action === "metadata" ? updated.platformNotes : updated.platformStatus
      )
    });
    return {
      id,
      notes: updated.platformNotes || "",
      status: updated.platformStatus
    };
  });
}

export async function updateCustomerUser(
  actor: Actor,
  id: string,
  status: "active" | "suspended"
) {
  const row = await userById(actor.tenantId, id);
  if (!row) throw new PortalError("notFound");
  return ownerDb.$transaction(async (tx) => {
    // Serialize owner changes within the customer tenant.
    await tx.$queryRaw`SELECT tenant_id FROM companies WHERE tenant_id = ${row.tenantId}::uuid FOR UPDATE`;
    const current = await tx.tenantUser.findUnique({
      where: { id },
      include: { user: true }
    });
    if (!current || current.removedAt) throw new PortalError("notFound");
    if (
      current.roleKey === "owner" &&
      current.platformStatus === "active" &&
      status !== "active"
    ) {
      const owners = await tx.tenantUser.count({
        where: {
          tenantId: current.tenantId,
          roleKey: "owner",
          platformStatus: "active",
          removedAt: null
        }
      });
      if (owners <= 1) throw new PortalError("lastAdmin");
    }
    const updated = await tx.tenantUser.update({
      where: { id },
      data: { platformStatus: status }
    });
    await auditWrite(tx, actor, {
      action: "statusChanged",
      domain: "users",
      target: current.user.email,
      companyId: current.tenantId,
      changes: changes("status", current.platformStatus, status)
    });
    return { id: updated.id, status: updated.platformStatus };
  });
}

export async function createInvite(
  actor: Actor,
  email: string,
  role: InvitablePlatformRole
) {
  const normalized = email.trim().toLowerCase();
  const matchingUsers = await ownerDb.user.findMany({
    where: {
      email: { equals: normalized, mode: "insensitive" },
      tenantUsers: {
        some: {
          removedAt: null,
          platformStatus: "active",
          tenant: { deletedAt: null, platformStatus: "active" }
        }
      }
    },
    select: { userId: true },
    take: 2
  });
  if (matchingUsers.length > 1)
    throw new PortalError("conflict", "Multiple accounts share this email.");
  const user = matchingUsers[0];
  if (!user)
    throw new PortalError(
      "accountRequired",
      "Invitee must have an existing account."
    );
  const member = await ownerDb.tenantUser.findUnique({
    where: {
      tenantId_userId: { tenantId: actor.tenantId, userId: user.userId }
    }
  });
  if (member && !member.removedAt) throw new PortalError("duplicate");
  return ownerDb.$transaction(async (tx) => {
    await tx.platformInvitation.updateMany({
      where: {
        tenantId: actor.tenantId,
        email: { equals: normalized, mode: "insensitive" },
        status: "pending"
      },
      data: { status: "cancelled" }
    });
    const token = randomBytes(32).toString("base64url");
    const invitation = await tx.platformInvitation.create({
      data: {
        tenantId: actor.tenantId,
        email: normalized,
        roleKey: role,
        tokenHash: tokenHash(token),
        invitedBy: actor.userId,
        expiresAt: new Date(Date.now() + 7 * 86400_000)
      }
    });
    await auditWrite(tx, actor, {
      action: "adminInvited",
      domain: "admin-team",
      target: normalized,
      changes: changes("role", null, role)
    });
    // Only the one-time response contains the raw token. The database stores its hash.
    return {
      id: invitation.id,
      email: normalized,
      role,
      status: "pending",
      createdAt: invitation.createdAt,
      token
    };
  });
}

export async function updateTeam(
  actor: Actor,
  id: string,
  action: "role" | "status" | "remove" | "resend" | "cancel",
  input: { role?: "owner" | "admin"; status?: "active" | "inactive" }
) {
  return ownerDb.$transaction(async (tx) => {
    await tx.$queryRaw`SELECT tenant_id FROM companies WHERE tenant_id = ${actor.tenantId}::uuid FOR UPDATE`;
    if (action === "resend" || action === "cancel") {
      const invite = await tx.platformInvitation.findFirst({
        where: {
          id,
          tenantId: actor.tenantId,
          status: "pending",
          expiresAt: { gt: new Date() }
        }
      });
      if (!invite) throw new PortalError("notFound");
      if (action === "cancel") {
        await tx.platformInvitation.update({
          where: { id },
          data: { status: "cancelled" }
        });
        await auditWrite(tx, actor, {
          action: "invitationCancelled",
          domain: "admin-team",
          target: invite.email
        });
        return { id, status: "cancelled" };
      }
      const token = randomBytes(32).toString("base64url");
      await tx.platformInvitation.update({
        where: { id },
        data: {
          tokenHash: tokenHash(token),
          expiresAt: new Date(Date.now() + 7 * 86400_000)
        }
      });
      await auditWrite(tx, actor, {
        action: "invitationResent",
        domain: "admin-team",
        target: invite.email
      });
      return { id, status: "pending", token };
    }
    const member = await tx.tenantUser.findFirst({
      where: { id, tenantId: actor.tenantId, removedAt: null },
      include: { user: { select: { email: true } } }
    });
    if (!member) throw new PortalError("notFound");
    if (member.roleKey === "owner") {
      throw new PortalError("forbidden");
    }

    if (
      member.userId === actor.userId &&
      (action === "remove" ||
        (action === "status" && input.status !== "active"))
    )
      throw new PortalError("forbidden");
    const data =
      action === "role"
        ? { roleKey: input.role! }
        : action === "status"
          ? { platformStatus: input.status! }
          : { removedAt: new Date() };
    const updated = await tx.tenantUser.update({ where: { id }, data });
    const field = action === "role" ? "role" : "status";
    await auditWrite(tx, actor, {
      action:
        action === "role"
          ? "roleChanged"
          : action === "status"
            ? "accessChanged"
            : "accessRemoved",
      domain: "admin-team",
      target: member.user.email,
      changes: changes(
        field,
        action === "role" ? member.roleKey : member.platformStatus,
        action === "role"
          ? updated.roleKey
          : action === "status"
            ? updated.platformStatus
            : "removed"
      )
    });
    return {
      id,
      role: updated.roleKey,
      status: updated.removedAt ? "removed" : updated.platformStatus
    };
  });
}

export async function invitationDetails(token: string) {
  const row = await ownerDb.platformInvitation.findUnique({
    where: { tokenHash: tokenHash(token) }
  });
  if (!row || row.status !== "pending") throw new PortalError("notFound");
  const [company, inviter] = await Promise.all([
    ownerDb.company.findUnique({ where: { id: row.tenantId } }),
    ownerDb.user.findUnique({
      where: { userId: row.invitedBy },
      select: { fullName: true, email: true }
    })
  ]);
  if (!company || company.deletedAt || company.businessType !== "platform")
    throw new PortalError("notFound");
  return {
    invitation: {
      organizationName: company.businessName,
      inviterName: inviter?.fullName || inviter?.email || "",
      email: row.email,
      status: row.expiresAt <= new Date() ? "expired" : "pending",
      expiresInDays: Math.max(
        0,
        Math.ceil((row.expiresAt.getTime() - Date.now()) / 86400_000)
      )
    }
  };
}

export async function acceptInvite(token: string, userId: string) {
  return ownerDb.$transaction(async (tx) => {
    const invite = await tx.platformInvitation.findUnique({
      where: { tokenHash: tokenHash(token) }
    });

    // Validate that the invitation exists and is still usable
    // before reading any properties from it.
    if (
      !invite ||
      invite.status !== "pending" ||
      invite.expiresAt <= new Date()
    ) {
      throw new PortalError("notFound");
    }

    // Platform invitations may only grant explicitly invitable
    // platform roles (currently "admin").
    if (!isInvitablePlatformRole(invite.roleKey)) {
      throw new PortalError("forbidden");
    }

    const platform = await tx.company.findFirst({
      where: {
        id: invite.tenantId,
        businessType: "platform",
        deletedAt: null,
        platformStatus: "active"
      },
      select: { id: true }
    });

    if (!platform) {
      throw new PortalError("notFound");
    }

    const user = await tx.user.findUnique({
      where: { userId }
    });

    if (!user || user.email.toLowerCase() !== invite.email.toLowerCase()) {
      throw new PortalError("forbidden");
    }

    const existing = await tx.tenantUser.findUnique({
      where: {
        tenantId_userId: {
          tenantId: invite.tenantId,
          userId
        }
      }
    });

    if (existing && !existing.removedAt) {
      throw new PortalError("duplicate");
    }

    const accepted = await tx.platformInvitation.updateMany({
      where: {
        id: invite.id,
        status: "pending"
      },
      data: {
        status: "accepted",
        acceptedAt: new Date()
      }
    });

    if (!accepted.count) {
      throw new PortalError("conflict");
    }

    await tx.tenantUser.upsert({
      where: {
        tenantId_userId: {
          tenantId: invite.tenantId,
          userId
        }
      },
      update: {
        roleKey: invite.roleKey,
        platformStatus: "active",
        removedAt: null
      },
      create: {
        tenantId: invite.tenantId,
        userId,
        roleKey: invite.roleKey,
        platformStatus: "active"
      }
    });

    await auditWrite(
      tx,
      {
        tenantId: invite.tenantId,
        userId,
        name: user.email,
        role: invite.roleKey
      },
      {
        action: "invitationAccepted",
        domain: "admin-team",
        target: user.email
      }
    );

    return { accepted: true };
  });
}

export async function updateSettings(
  actor: Actor,
  input: {
    name: string;
    supportEmail: string;
    language: "en" | "ar";
    currency: string;
  }
) {
  return ownerDb.$transaction(async (tx) => {
    const before = await tx.company.findUniqueOrThrow({
      where: { id: actor.tenantId }
    });
    const existing = await tx.appConfig.findUnique({
      where: { key: "platform.supportEmail" }
    });
    await tx.company.update({
      where: { id: actor.tenantId },
      data: {
        businessName: input.name.trim(),
        preferredLanguage: input.language
      }
    });
    await tx.appConfig.upsert({
      where: { key: "platform.supportEmail" },
      create: {
        key: "platform.supportEmail",
        value: input.supportEmail.trim()
      },
      update: { value: input.supportEmail.trim() }
    });
    await auditWrite(tx, actor, {
      action: "settingsUpdated",
      domain: "settings",
      target: actor.tenantId,
      changes: [
        ...changes("name", before.businessName, input.name.trim()),
        ...changes("supportEmail", existing?.value, input.supportEmail.trim()),
        ...changes("language", before.preferredLanguage, input.language)
      ]
    });
    return {
      ...input,
      name: input.name.trim(),
      supportEmail: input.supportEmail.trim()
    };
  });
}

export async function updateProfile(
  actor: Actor,
  name: string,
  language: "en" | "ar"
) {
  return ownerDb.$transaction(async (tx) => {
    const before = await tx.user.findUniqueOrThrow({
      where: { userId: actor.userId }
    });
    const updated = await tx.user.update({
      where: { userId: actor.userId },
      data: { fullName: name.trim(), preferredLanguage: language }
    });
    await auditWrite(tx, actor, {
      action: "profileUpdated",
      domain: "account",
      target: actor.userId,
      changes: [
        ...changes("name", before.fullName, updated.fullName),
        ...changes(
          "language",
          before.preferredLanguage,
          updated.preferredLanguage
        )
      ]
    });
    return {
      id: updated.userId,
      name: updated.fullName,
      language: updated.preferredLanguage
    };
  });
}

export async function changePassword(
  actor: Actor,
  current: string,
  next: string
) {
  const user = await ownerDb.user.findUnique({
    where: { userId: actor.userId }
  });
  if (
    !user ||
    !(await verifyPassword(current, user.passwordHash)) ||
    current === next
  )
    throw new PortalError("invalid");
  const passwordHash = await hashPassword(next);
  return ownerDb.$transaction(async (tx) => {
    // Optimistic guard prevents a second password update using the old hash.
    const result = await tx.user.updateMany({
      where: { userId: actor.userId, passwordHash: user.passwordHash },
      data: { passwordHash, sessionVersion: { increment: 1 } }
    });
    if (!result.count) throw new PortalError("conflict");
    await tx.authSession.updateMany({
      where: { userId: actor.userId, revokedAt: null },
      data: { revokedAt: new Date() }
    });
    await auditWrite(tx, actor, {
      action: "passwordChanged",
      domain: "account",
      target: actor.userId
    });
    return { passwordChanged: true, reauthenticate: true };
  });
}

export async function sessions(actor: Actor, sessionId?: string) {
  if (!sessionId) return { items: [], available: false };
  const items = await ownerDb.authSession.findMany({
    where: {
      userId: actor.userId,
      expiresAt: { gt: new Date() },
      revokedAt: null
    },
    orderBy: { lastActive: "desc" },
    take: 50
  });
  return {
    available: true,
    items: items.map((row) => ({
      id: row.id,
      device: row.device,
      lastActive: row.lastActive,
      current: row.id === sessionId
    }))
  };
}
export async function revokeSession(
  actor: Actor,
  sessionId: string | undefined,
  target?: string
) {
  if (!sessionId) throw new PortalError("invalid");
  if (target && target === sessionId) throw new PortalError("invalid");
  return ownerDb.$transaction(async (tx) => {
    const result = await tx.authSession.updateMany({
      where: {
        userId: actor.userId,
        revokedAt: null,
        ...(target ? { id: target } : { id: { not: sessionId } })
      },
      data: { revokedAt: new Date() }
    });
    if (target && !result.count) throw new PortalError("notFound");
    await auditWrite(tx, actor, {
      action: "sessionsRevoked",
      domain: "account",
      target: actor.userId
    });
    return { revoked: result.count };
  });
}
