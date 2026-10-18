import { unsupportedSettingsAction } from './settingsCapabilities.js';
import { normalizeRoles } from '../../auth/permissions/rolePermissions.js';

const roleOrder = ['admin', 'editor', 'viewer'];
const primaryRole = (roles = []) => roleOrder.find((role) => normalizeRoles(roles).includes(role)) || normalizeRoles(roles)[0] || null;

export const teamApi = {
  listMembers: async ({ user, roles = [], companyId } = {}) => ({
    members: user ? [{
      id: user.id || user.userId || user.user_id || 'current-user',
      name: user.full_name || user.fullName || user.displayName || user.name || user.profile?.fullName || '',
      email: user.email || user.emailAddress || user.profile?.email || '',
      avatarUrl: user.avatarUrl || user.avatar || user.picture || null,
      role: primaryRole(roles),
      status: user.membership?.status || null,
      joinedAt: user.membership?.joined_at || user.joinedAt || null,
      isCurrentUser: true,
    }] : [],
    invitations: [],
    available: false,
    invitationsAvailable: false,
    companyId: companyId || null,
    capabilities: { invite: false, changeRole: false, removeMember: false, resendInvitation: false, cancelInvitation: false },
  }),
  inviteMember: unsupportedSettingsAction,
  changeRole: unsupportedSettingsAction,
  removeMember: unsupportedSettingsAction,
};
