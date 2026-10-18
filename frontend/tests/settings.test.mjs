import test from 'node:test';
import assert from 'node:assert/strict';
import { getSettingsPermissions } from '../src/features/settings/permissions/settingsPermissions.js';
import { profileApi } from '../src/features/settings/api/profileApi.js';
import { companyApi } from '../src/features/settings/api/companyApi.js';
import { teamApi } from '../src/features/settings/api/teamApi.js';
import { securityApi } from '../src/features/settings/api/securityApi.js';
import { preferencesApi } from '../src/features/settings/api/preferencesApi.js';

test('permissions normalize known roles and never promote legacy/unknown roles',()=>{
 for(const role of ['ADMIN',' admin '])assert.equal(getSettingsPermissions([role]).canInviteMembers,true);
 for(const role of ['EDITOR','VIEWER','owner','manager','accountant','staff','unknown']){
  const permissions=getSettingsPermissions([role]);
  for(const action of ['canEditCompany','canInviteMembers','canManageRoles','canRemoveMembers'])assert.equal(permissions[action],false);
  assert.equal(permissions.canManageOwnSecurity,true);
 }
 assert.equal(getSettingsPermissions(['owner']).role,'owner');
 assert.equal(getSettingsPermissions([]).canInviteMembers,false);
});
test('unsupported mutations reject instead of entering success state or echoing payload',async()=>{
 for(const method of [profileApi.updateProfile,companyApi.updateCompany,teamApi.inviteMember,teamApi.changeRole,teamApi.removeMember,securityApi.changePassword,preferencesApi.updateNotificationPreferences])await assert.rejects(method({privateValue:'test'}),{code:'SETTINGS_UNAVAILABLE'});
});
test('schema values and membership metadata stay truthful',async()=>{
 const user={user_id:'u1',full_name:'Account Name',createdAt:'2020-01-01',company:{tenant_id:'t1',business_name:'Company',primary_currency:'JOD',country_code:'JO'}};
 assert.equal((await profileApi.getProfile({user})).profile.fullName,'Account Name');
 assert.equal((await companyApi.getCompany({user})).company.currency,'JOD');
 const team=await teamApi.listMembers({user,roles:['manager']});
 assert.equal(team.available,false);assert.equal(team.invitationsAvailable,false);
 assert.equal(team.members[0].role,'manager');assert.equal(team.members[0].joinedAt,null);assert.equal(team.members[0].status,null);
});
