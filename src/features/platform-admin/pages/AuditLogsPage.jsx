import { useState } from 'react';
import Modal from '../../../shared/components/ui/Modal.jsx';
import { useAdminQuery, useAdminText } from '../components/AdminContext.jsx';
import { Heading, Badge, DateValue, Button, DefinitionList } from '../components/AdminUI.jsx';
import { AdminTable, useTableParams } from '../components/AdminTable.jsx';
import { ChangesTable } from './PlansPage.jsx';

export function AuditLogsPage() {
  const { t } = useAdminText(), table = useTableParams(), query = useAdminQuery('audit-logs', table.params), [selected, setSelected] = useState(null);
  return <><Heading title="auditLogs" description="auditLogsDescription" /><AdminTable title={t('auditLogs')} query={query} table={table} dateFilters filters={[{ key: 'actor', options: query.data?.facets?.actors || [] }, { key: 'action', options: ['planUpdated', 'statusChanged', 'metadataUpdated', 'adminInvited', 'roleChanged', 'accessChanged', 'accessRemoved', 'invitationResent', 'invitationCancelled', 'settingsUpdated', 'subscriptionCancelled'] }, { key: 'targetType', options: ['companies', 'users', 'subscriptions', 'plans', 'admin-team', 'settings'] }]} columns={[{ key: 'createdAt', label: 'timestamp', render: row => <DateValue value={row.createdAt} time /> }, { key: 'actor' }, { key: 'actorRole', render: row => <Badge value={row.actorRole} /> }, { key: 'action', render: row => t(row.action) }, { key: 'targetType', render: row => t(row.targetType) }, { key: 'target' }, { key: 'result', render: row => <Badge value={row.result} /> }]} rowAction={row => <Button size="sm" variant="ghost" onClick={() => setSelected(row)}>{t('view')}</Button>} /><Modal className="pa-dialog" isOpen={Boolean(selected)} title={t('details')} closeLabel={t('close')} maxWidth="720px" onClose={() => setSelected(null)}>{selected && <><DefinitionList items={[[t('actor'), selected.actor], [t('action'), t(selected.action)], [t('target'), selected.target], [t('timestamp'), <DateValue value={selected.createdAt} time />]]} /><p>{t('noSensitive')}</p><ChangesTable changes={selected.changes || []} /></>}</Modal></>;
}
