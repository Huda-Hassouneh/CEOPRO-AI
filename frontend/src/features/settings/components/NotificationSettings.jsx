import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import { NOTIFICATION_GROUPS } from '../api/preferencesApi.js';
import { useUpdateNotificationPreferences } from '../hooks/useNotificationPreferences.js';
import { SettingsSection } from './SettingsSection.jsx';

const FREQUENCIES = ['off', 'daily', 'weekly'];

// Which alert groups show in the bell and go into the email summary, and how
// often the summary is sent. Every change saves straight away.
export function NotificationSettings({ query, companyId, t, onNotice }) {
  const update = useUpdateNotificationPreferences(companyId);
  if (query.isPending) return <Skeleton height="260px" variant="rectangular" />;
  if (query.isError || !query.data?.preferences) return <SettingsSection title={t('settings.notifications.title')}><p className="settings-inline-error">{t('settings.notifications.loadError')}</p></SettingsSection>;

  const { preferences, emailVerified, emailDeliveryAvailable } = query.data;
  const save = (patch) => update.mutate(patch, { onError: () => onNotice?.('error', t('settings.notifications.saveFailed')) });
  const summaryOff = preferences.email_frequency === 'off';

  return (
    <SettingsSection title={t('settings.notifications.title')} subtitle={t('settings.notifications.subtitle')}>
      <fieldset className="settings-language-options settings-notification-frequency">
        <legend>{t('settings.notifications.frequency.label')}</legend>
        {FREQUENCIES.map((value) => (
          <label className={preferences.email_frequency === value ? 'is-selected' : ''} key={value}>
            <input type="radio" name="settings-notification-frequency" value={value} checked={preferences.email_frequency === value} onChange={() => save({ email_frequency: value })} />
            <span><strong>{t(`settings.notifications.frequency.${value}`)}</strong><small>{t(`settings.notifications.frequency.${value}Hint`)}</small></span>
          </label>
        ))}
      </fieldset>
      {!summaryOff && !emailVerified ? <p className="settings-capability-note">{t('settings.notifications.emailUnverified')}</p> : null}
      {!summaryOff && emailVerified && !emailDeliveryAvailable ? <p className="settings-capability-note">{t('settings.notifications.emailUnavailable')}</p> : null}
      <div className="settings-team-table-wrap" tabIndex={0} role="region" aria-label={t('common.scrollableTable')}>
        <table className="settings-team-table settings-notification-table">
          <thead>
            <tr>
              <th scope="col">{t('settings.notifications.columns.group')}</th>
              <th scope="col">{t('settings.notifications.columns.inApp')}</th>
              <th scope="col">{t('settings.notifications.columns.email')}</th>
            </tr>
          </thead>
          <tbody>
            {NOTIFICATION_GROUPS.map((group) => (
              <tr key={group}>
                <th scope="row"><span><strong>{t(`settings.notifications.groups.${group}.title`)}</strong><small>{t(`settings.notifications.groups.${group}.description`)}</small></span></th>
                {['in_app', 'email'].map((channel) => (
                  <td key={channel}>
                    <input
                      type="checkbox"
                      aria-label={`${t(`settings.notifications.groups.${group}.title`)} - ${t(`settings.notifications.columns.${channel === 'in_app' ? 'inApp' : 'email'}`)}`}
                      checked={Boolean(preferences[channel]?.[group])}
                      disabled={channel === 'email' && summaryOff}
                      onChange={(event) => save({ [channel]: { [group]: event.target.checked } })}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {summaryOff ? <p className="settings-capability-note">{t('settings.notifications.emailOffNote')}</p> : null}
    </SettingsSection>
  );
}
