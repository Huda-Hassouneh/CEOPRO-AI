// Development-only display data. This is not an API response contract.
export const invitationPreview = Object.freeze({
  status: 'active',
  organizationName: 'Acme Corporation',
  inviterName: 'Sarah Ahmad',
  expiresInDays: 6,
});

export const expiredInvitationPreview = Object.freeze({
  status: 'expired',
});

export function getInvitationPreview(state = 'active') {
  return state === 'expired' ? expiredInvitationPreview : invitationPreview;
}
