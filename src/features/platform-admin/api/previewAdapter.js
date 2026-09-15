import { createPreviewData } from '../config/previewData.js';
import { can, requirePermission, protectLastSuperAdmin, PLATFORM_ROLES } from '../permissions/platformPermissions.js';
import { PREVIEW_PLANS, replacePreviewPlan } from '../../../shared/catalog/planCatalog.js';
import { fail, validEmail, validatePlan } from './validation.js';
import { collectChanges } from './changes.js';

const db = createPreviewData();
let role = null;
export const setPreviewRole = next => { role = PLATFORM_ROLES.includes(next) ? next : null; };
export const getPreviewPrincipal = () => role ? { ...db['admin-team'].find(m => m.id === 'preview-admin'), role } : null;
const principal = () => getPreviewPrincipal();
const readPermissions = { overview: 'platform.overview.read', companies: 'companies.read', users: 'users.read', subscriptions: 'subscriptions.read', plans: 'plans.read', 'admin-team': 'adminTeam.read', 'audit-logs': 'auditLogs.read', settings: 'platformSettings.read' };
const delay = () => new Promise(resolve => setTimeout(resolve, 180));
const clone = value => structuredClone(value);
function audit(action, domain, id, before, after, companyId) {
  db['audit-logs'].unshift({ id: crypto.randomUUID(), createdAt: new Date().toISOString(), actor: principal().name, actorRole: principal().role, action, targetType: domain, target: id, companyId: companyId || (domain === 'companies' ? id : null), result: 'success', changes: collectChanges(before, after || {}) });
}
export function paginate(rows, query = {}) {
  let result = rows.filter(row => (!query.q || [row.name, row.email, row.company, row.actor, row.target].some(v => String(v || '').toLowerCase().includes(query.q.toLowerCase()))) && ['planId', 'status', 'subscriptionStatus', 'country', 'role', 'companyId', 'billingPeriod', 'actor', 'action', 'targetType'].every(key => !query[key] || String(row[key]) === query[key]) && (!query.from || row.createdAt >= query.from) && (!query.to || row.createdAt.slice(0, 10) <= query.to));
  const sort = query.sort || 'createdAt';
  result.sort((a, b) => String(a[sort] ?? '').localeCompare(String(b[sort] ?? ''), undefined, { numeric: true }) * (query.direction === 'asc' ? 1 : -1));
  const total = result.length, pageSize = Math.min(50, Math.max(1, Number(query.pageSize) || 8));
  const page = Math.min(Math.max(1, Number(query.page) || 1), Math.max(1, Math.ceil(total / pageSize)));
  return { items: clone(result.slice((page - 1) * pageSize, page * pageSize)), total, page, pageSize, preview: true };
}
export const previewAdapter = {
  me: async () => { await delay(); return clone(principal()); },
  list: async (domain, query = {}) => {
    await delay(); requirePermission(principal(), readPermissions[domain]);
    if (!(domain in readPermissions)) fail('forbidden');
    if (domain === 'overview') {
      const months = ['2026-04', '2026-05', '2026-06', '2026-07', '2026-08', '2026-09'];
      return { companies: db.companies.length, users: db.users.length, active: db.subscriptions.filter(s => s.status === 'active').length, trials: db.subscriptions.filter(s => s.status === 'trial').length, growth: months.map(month => ({ month, companies: db.companies.filter(c => c.createdAt.startsWith(month)).length, users: db.users.filter(u => u.createdAt.startsWith(month)).length })), distribution: Object.keys(PREVIEW_PLANS).map(planId => ({ planId, count: db.subscriptions.filter(s => s.planId === planId).length })), recentCompanies: clone(db.companies.slice(-4).reverse()), activity: clone(db['audit-logs'].slice(0, 5)), preview: true };
    }
    if (domain === 'settings') return clone(db.settings);
    if (domain === 'plans') return { items: clone(Object.values(PREVIEW_PLANS)), total: 3, preview: true };
    return { ...paginate(db[domain], query), facets: { companies: db.companies.map(c => ({ value: c.id, label: c.name })), actors: [...new Set(db['audit-logs'].map(a => a.actor))].map(a => ({ value: a, label: a })) } };
  },
  detail: async (domain, id) => {
    await delay(); requirePermission(principal(), readPermissions[domain]);
    const row = domain === 'plans' ? PREVIEW_PLANS[id] : db[domain]?.find(r => r.id === id);
    if (!row) fail('notFound');
    if (domain === 'companies') return clone({ ...row, subscription: db.subscriptions.find(s => s.companyId === id), limits: PREVIEW_PLANS[row.planId].limits || {}, activity: db['audit-logs'].filter(a => a.companyId === id).slice(0, 20) });
    return clone(row);
  },
  mutate: async (domain, id, action, payload = {}) => {
    await delay();
    const permissions = { 'companies.metadata': 'companies.update', 'companies.status': 'companies.status.manage', 'users.status': 'users.manage', 'subscriptions.cancel': 'subscriptions.manage', 'plans.update': 'plans.manage', 'admin-team.invite': 'adminTeam.invite', 'admin-team.role': 'adminTeam.roles.manage', 'admin-team.status': 'adminTeam.roles.manage', 'admin-team.remove': 'adminTeam.remove', 'admin-team.resend': 'adminTeam.invite', 'admin-team.cancel': 'adminTeam.remove', 'settings.update': 'platformSettings.manage' };
    const permission = permissions[`${domain}.${action}`];
    if (!permission) fail('forbidden');
    requirePermission(principal(), permission);
    if (domain === 'plans') {
      validatePlan(payload); const before = clone(PREVIEW_PLANS[id]);
      if (!before || payload.id !== id) fail('invalid');
      if (before.version !== payload.version) fail('conflict');
      const next = { ...payload, version: before.version + 1, updatedAt: new Date().toISOString() };
      replacePreviewPlan(next); audit('planUpdated', domain, id, before, next); return clone(next);
    }
    if (domain === 'settings') {
      if (!payload.name?.trim() || !validEmail(payload.supportEmail) || !['en', 'ar'].includes(payload.language) || payload.currency !== 'USD') fail('invalid');
      const before = clone(db.settings); db.settings = { name: payload.name.trim(), supportEmail: payload.supportEmail.trim(), language: payload.language, currency: 'USD' }; audit('settingsUpdated', domain, 'platform', before, db.settings); return clone(db.settings);
    }
    if (domain === 'admin-team' && action === 'invite') {
      if (!validEmail(payload.email) || !PLATFORM_ROLES.includes(payload.role)) fail('invalid');
      if (db[domain].some(m => m.email.toLowerCase() === payload.email.trim().toLowerCase())) fail('duplicate');
      const member = { id: crypto.randomUUID(), name: '', email: payload.email.trim(), role: payload.role, status: 'pending', createdAt: new Date().toISOString() }; db[domain].push(member); audit('adminInvited', domain, member.email, {}, { role: member.role, status: member.status }); return clone(member);
    }
    const row = db[domain]?.find(r => r.id === id); if (!row) fail('notFound');
    const before = clone(row);
    if (domain === 'admin-team') {
      const changes = action === 'role' ? { role: payload.role } : action === 'status' ? { status: payload.status } : { remove: ['remove', 'cancel'].includes(action) };
      if (action === 'role' && !PLATFORM_ROLES.includes(payload.role)) fail('invalid');
      if (action === 'status' && !['active', 'inactive'].includes(payload.status)) fail('invalid');
      if (['resend', 'cancel'].includes(action) && row.status !== 'pending') fail('invalid');
      if (row.status === 'pending' && ['status', 'role'].includes(action)) fail('invalid');
      protectLastSuperAdmin(db[domain], row, changes);
      if (changes.remove) db[domain] = db[domain].filter(m => m.id !== id);
      else if (action !== 'resend') Object.assign(row, changes);
      audit({ role: 'roleChanged', status: 'accessChanged', remove: 'accessRemoved', cancel: 'invitationCancelled', resend: 'invitationResent' }[action], domain, row.email, before, changes);
      if (id === 'preview-admin') role = action === 'role' ? payload.role : (changes.remove || payload.status === 'inactive') ? null : role;
    } else if (action === 'metadata') {
      if (typeof payload.notes !== 'string' || payload.notes.length > 2000) fail('invalid');
      row.notes = payload.notes.trim(); audit('metadataUpdated', domain, id, before, { notes: row.notes });
    } else if (action === 'cancel') {
      if (!['active', 'trial'].includes(row.status)) fail('invalid');
      row.status = 'cancelled'; db.companies.find(c => c.id === row.companyId).subscriptionStatus = 'cancelled'; audit('subscriptionCancelled', domain, id, before, { status: row.status }, row.companyId);
    } else {
      if (!['active', 'suspended'].includes(payload.status)) fail('invalid');
      row.status = payload.status; audit('statusChanged', domain, id, before, { status: row.status }, row.companyId);
    }
    return clone(row);
  },
  account: async (action, payload = {}) => {
    await delay(); requirePermission(principal());
    if (action === 'sessions') return { items: clone(db.sessions), available: true };
    if (action === 'profile') {
      if (!payload.name?.trim() || !['en', 'ar'].includes(payload.language)) fail('invalid');
      Object.assign(db['admin-team'][0], { name: payload.name.trim(), language: payload.language }); return clone(principal());
    }
    if (action === 'password') { if (!payload.currentPassword || payload.newPassword?.length < 12 || payload.currentPassword === payload.newPassword) fail('invalid'); return { preview: true }; }
    if (action === 'revoke') { if (db.sessions.find(s => s.id === payload.id)?.current) fail('invalid'); db.sessions = db.sessions.filter(s => s.id !== payload.id); return { preview: true }; }
    if (action === 'revokeOthers') { db.sessions = db.sessions.filter(s => s.current); return { preview: true }; }
    fail('invalid');
  },
};
