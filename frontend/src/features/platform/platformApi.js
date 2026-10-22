import httpClient from '../../shared/lib/httpClient.js';
const unwrap = (promise) => promise.then((response) => response.data);
const id = encodeURIComponent;
export const platformApi = Object.freeze({
  me: () => unwrap(httpClient.get('/platform/me')),
  read: (area, offset = 0, search) => {
    if (!['overview', 'companies', 'users', 'team', 'audit', 'settings'].includes(area)) throw new Error('Unknown platform area');
    const params = { limit: 50, offset };
    if (['companies', 'users'].includes(area) && search !== undefined) params.search = search;
    return unwrap(httpClient.get(`/platform/${area}`, { params }));
  },
  detail: (area, value) => {
    if (!['companies', 'users'].includes(area)) throw new Error('Unknown detail area');
    return unwrap(httpClient.get(`/platform/${area}/${id(value)}`));
  },
  company: (value, body) => unwrap(httpClient.patch(`/platform/companies/${id(value)}/metadata`, body)),
  companyStatus: (value, body) => unwrap(httpClient.patch(`/platform/companies/${id(value)}/status`, body)),
  userStatus: (value, body) => unwrap(httpClient.patch(`/platform/users/${id(value)}/status`, body)),
  membershipStatus: (value, body) => unwrap(httpClient.patch(`/platform/memberships/${id(value)}/status`, body)),
  invite: (body) => unwrap(httpClient.post('/platform/team/invitations', body)),
  invitationAction: (value, action, reason) => {
    if (!['resend', 'cancel'].includes(action)) throw new Error('Unknown invitation action');
    return unwrap(httpClient.post(`/platform/team/invitations/${id(value)}/${action}`, { reason }));
  },
  member: (value, body) => unwrap(httpClient.patch(`/platform/team/${id(value)}`, body)),
  transfer: (value, reason) => unwrap(httpClient.post(`/platform/owner-transfer/${id(value)}`, { reason })),
  settings: (body) => unwrap(httpClient.patch('/platform/settings', body)),
  approve: (body) => unwrap(httpClient.post('/platform/financial-approvals', body)),
  invitation: (token) => unwrap(httpClient.get(`/platform/invitations/${id(token)}`)),
  accept: (token, body) => unwrap(httpClient.post(`/platform/invitations/${id(token)}/accept`, body)),
});

// Dependency failures are retryable; they are not evidence that an invitation is invalid.
export const platformInvitationErrorKey = (error) => {
  const status = error?.response?.status;
  if (status === 422) return 'platform.newCredentials';
  if (status === 409) return 'platform.conflict';
  if (status === 404) return 'platform.invitationInvalid';
  return 'platform.failed';
};
