import httpClient from '../../../shared/lib/httpClient.js';

// The real backend endpoints - backend/src/ai/routers/settings.py's
// GET /settings/team/members, POST /settings/team/invitations,
// PATCH/DELETE /settings/team/members/{id}. Every row list_team_members
// returns is already an active (non-removed) membership - there is no
// per-member status concept server-side beyond that, so every real row
// maps to 'active' (matches settings.team.status.active), never a
// fabricated 'pending'/'invited' state. There is no GET endpoint to list
// pending invitations (only POST to create one) - invitations always
// stays [] and invitationsAvailable stays false, honestly, not because
// invites don't work.
function toMember(row, currentUserId) {
  return {
    id: row.tenant_user_id,
    name: row.full_name || '',
    email: row.email || '',
    avatarUrl: null,
    role: row.role_key,
    status: 'active',
    joinedAt: row.joined_at,
    isCurrentUser: row.user_id === currentUserId,
  };
}

export const teamApi = {
  listMembers: async ({ user, companyId } = {}) => {
    const response = await httpClient.get('/settings/team/members');
    const currentUserId = user?.id || user?.userId || user?.user_id || null;
    return {
      members: (response.data?.members ?? []).map((row) => toMember(row, currentUserId)),
      invitations: [],
      available: true,
      invitationsAvailable: false,
      companyId: companyId || null,
      capabilities: { invite: true, changeRole: true, removeMember: true, resendInvitation: false, cancelInvitation: false },
    };
  },

  // Owner/admin only server-side (settings.py::invite_team_member).
  inviteMember: async ({ email, role } = {}) => {
    await httpClient.post('/settings/team/invitations', { email, role_key: role });
    return { sent: true };
  },

  // Owner/admin only server-side; rejects demoting the tenant's last owner.
  changeRole: async ({ tenantUserId, role } = {}) => {
    await httpClient.patch(`/settings/team/members/${encodeURIComponent(tenantUserId)}`, { role_key: role });
    return { changed: true };
  },

  // Owner/admin only server-side; rejects removing the tenant's last owner.
  removeMember: async ({ tenantUserId } = {}) => {
    await httpClient.delete(`/settings/team/members/${encodeURIComponent(tenantUserId)}`);
    return { removed: true };
  },
};
