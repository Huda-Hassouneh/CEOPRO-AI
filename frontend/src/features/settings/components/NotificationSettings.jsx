import {useQuery,useMutation,useQueryClient} from '@tanstack/react-query';
import {useAuthStore} from '../../auth/store/authStore.js';
import http from '../../../shared/lib/httpClient.js';
import {SettingsSection} from './SettingsSection.jsx';
export function NotificationSettings({t}){
 const tenant=useAuthStore(s=>s.tenantId),user=useAuthStore(s=>s.user?.id??s.user?.user_id),client=useQueryClient(),key=['notification-preferences',tenant,user];
 const query=useQuery({queryKey:key,enabled:Boolean(tenant&&user),queryFn:async({signal})=>(await http.get('/notifications/preferences',{signal})).data.data,retry:false});
 const mutation=useMutation({mutationFn:({category,enabled})=>http.put('/notifications/preferences/'+category,{enabled}),retry:false,onSuccess:()=>client.invalidateQueries({queryKey:key})});
 return <SettingsSection title={t('settings.notifications.title')} subtitle={t('notificationPreferences.description')}>
 {query.isPending&&<p role="status">{t('smartAlerts.loading')}</p>}
 {(query.isError||mutation.isError)&&<p role="alert">{t('smartAlerts.error')}</p>}
 {query.data?.map(p=><p key={p.category}><label><input type="checkbox" checked={p.enabled} disabled={mutation.isPending} onChange={e=>mutation.mutate({category:p.category,enabled:e.target.checked})}/>{t('notificationPreferences.'+p.category)}</label></p>)}
 <p>{t('notificationPreferences.mandatory')}</p>
 </SettingsSection>;
}
