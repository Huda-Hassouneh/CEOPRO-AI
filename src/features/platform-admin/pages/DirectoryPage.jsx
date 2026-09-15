import { Link } from 'react-router-dom';
import { ArrowUpRight } from 'lucide-react';
import { useAdminQuery, useAdminText } from '../components/AdminContext.jsx';
import { Heading, Badge, DateValue, Identity } from '../components/AdminUI.jsx';
import { AdminTable, useTableParams } from '../components/AdminTable.jsx';

export function DirectoryPage({ domain }) {
  const { t } = useAdminText(), table = useTableParams(), query = useAdminQuery(domain, table.params);
  const translated = key => ({ key, render: row => <Badge value={row[key]} /> });
  const created = { key: 'createdAt', render: row => <DateValue value={row.createdAt} /> };
  const company = { key: 'company', render: row => <Link to={`/admin/companies/${row.companyId}`}>{row.company}</Link> };
  const config = {
    companies: { columns: [{ key: 'name', label: 'company', render: row => <Identity name={row.name} to={`/admin/companies/${row.id}`} /> }, { key: 'industry', render: row => t(row.industry) }, { key: 'country', render: row => t(row.country) }, translated('planId'), translated('subscriptionStatus'), { key: 'users' }, { key: 'products' }, { key: 'competitors' }, created, { ...translated('status'), label: 'statusLabel' }], filters: [{ key: 'planId', options: ['standard', 'pro', 'custom'] }, { key: 'subscriptionStatus', options: ['active', 'trial', 'cancelled'] }, { key: 'status', options: ['active', 'suspended'] }, { key: 'country', options: ['JO', 'AE', 'SA'] }] },
    users: { columns: [{ key: 'name', render: row => <Identity name={row.name} email={row.email} to={`/admin/users/${row.id}`} /> }, company, { ...translated('role'), label: 'companyRole' }, translated('status'), { ...created, label: 'joined' }], filters: [{ key: 'companyId', label: 'company', options: query.data?.facets?.companies || [] }, { key: 'role', options: ['owner', 'admin', 'manager', 'accountant', 'staff'] }, { key: 'status', options: ['active', 'suspended'] }] },
    subscriptions: { columns: [company, translated('planId'), { key: 'billingPeriod', render: row => t(row.billingPeriod) }, translated('status'), created, { key: 'trialEndsAt', render: row => <DateValue value={row.trialEndsAt} /> }, { key: 'renewsAt', render: row => <DateValue value={row.renewsAt} /> }], filters: [{ key: 'planId', options: ['standard', 'pro', 'custom'] }, { key: 'status', options: ['active', 'trial', 'cancelled'] }, { key: 'billingPeriod', options: ['monthly', 'three-months', 'six-months'] }] },
  }[domain];
  return <><Heading title={domain} description={`${domain}Description`} /><AdminTable title={t(domain)} query={query} table={table} {...config} rowAction={row => <Link className="pa-row-action" aria-label={`${t('view')}: ${row.name || row.company}`} to={`/admin/${domain}/${row.id}`}><ArrowUpRight size={17} /></Link>} /></>;
}
