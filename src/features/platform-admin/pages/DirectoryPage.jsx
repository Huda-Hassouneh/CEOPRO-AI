import { Link } from 'react-router-dom';
import { ArrowUpRight } from 'lucide-react';
import { useAdminQuery, useAdminText } from '../components/AdminContext.jsx';
import { Heading, Badge, DateValue, Identity } from '../components/AdminUI.jsx';
import { AdminTable, useTableParams } from '../components/AdminTable.jsx';

export function DirectoryPage({ domain }) {
  const { t } = useAdminText();
  const table = useTableParams();
  const query = useAdminQuery(domain, table.params);
  const created = { key: 'createdAt', render: row => <DateValue value={row.createdAt} /> };
  const status = { key: 'status', label: 'statusLabel', render: row => <Badge value={row.status} /> };
  const config = domain === 'companies' ? {
    columns: [
      { key: 'name', label: 'company', render: row => <Identity name={row.name} to={`/admin/companies/${row.id}`} /> },
      { key: 'industry', render: row => row.industry || t('unknown'), sortable: false },
      { key: 'country', render: row => row.country || t('unknown') },
      { key: 'planId', render: row => row.planName || t('unknown'), sortable: false },
      { key: 'subscriptionStatus', render: row => row.subscriptionStatus ? <Badge value={row.subscriptionStatus} /> : t('unknown'), sortable: false },
      ...['users', 'products', 'competitors'].map(key => ({ key, sortable: false })),
      created, status,
    ],
    filters: [
      { key: 'planId', options: query.data?.facets?.plans || [] },
      { key: 'subscriptionStatus', options: ['active', 'trial', 'trialing', 'cancelled'] },
      { key: 'status', options: ['active', 'suspended'] },
      { key: 'country', options: query.data?.facets?.countries || [] },
    ],
  } : {
    columns: [
      { key: 'name', render: row => <Identity name={row.name} email={row.email} to={`/admin/users/${row.id}`} /> },
      { key: 'company', render: row => <Link to={`/admin/companies/${row.companyId}`}>{row.company}</Link> },
      { key: 'role', label: 'companyRole', render: row => <Badge value={row.role} /> },
      status, { ...created, label: 'joined' },
    ],
    filters: [
      { key: 'companyId', label: 'company', options: query.data?.facets?.companies || [] },
      { key: 'role', options: ['owner', 'admin', 'manager', 'accountant', 'staff'] },
      { key: 'status', options: ['active', 'suspended'] },
    ],
  };
  return <>
    <Heading title={domain} description={`${domain}Description`} />
    <AdminTable title={t(domain)} query={query} table={table} {...config}
      rowAction={row => <Link className="pa-row-action" aria-label={`${t('view')}: ${row.name}`}
        to={`/admin/${domain}/${row.id}`}><ArrowUpRight size={17} /></Link>} />
  </>;
}
