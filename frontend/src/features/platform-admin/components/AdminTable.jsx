import { useSearchParams } from 'react-router-dom';
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight } from 'lucide-react';
import { useAdminText } from './AdminContext.jsx';
import { Button, Empty, SelectField, Field, QueryState } from './AdminUI.jsx';

export function useTableParams(scope = {}) {
  const [search, setSearch] = useSearchParams();
  const params = { ...Object.fromEntries(search), ...scope };
  const update = (key, value) => setSearch(old => { const next = new URLSearchParams(old); value ? next.set(key, value) : next.delete(key); if (key !== 'page') next.delete('page'); return next; }, { replace: true });
  const sortBy = key => setSearch(old => { const next = new URLSearchParams(old); next.set('sort', key); next.set('direction', (old.get('sort') || 'createdAt') === key && old.get('direction') === 'asc' ? 'desc' : 'asc'); next.delete('page'); return next; }, { replace: true });
  return { params, update, sortBy, clear: () => setSearch({}, { replace: true }) };
}
export function AdminTable({ query, columns, table, filters = [], title, rowAction, dateFilters = false }) {
  const { t } = useAdminText(), { params, update, clear } = table;
  const result = query.data || { items: [], total: 0, page: 1, pageSize: 8 };
  const pages = Math.max(1, Math.ceil(result.total / result.pageSize));
  const filterOptions = options => [{ value: '', label: t('all') }, ...options.map(o => typeof o === 'string' ? { value: o, label: t(o) } : o)];
  return <section className="pa-panel pa-directory"><div className="pa-filters"><Field label={t('search')} type="search" value={params.q || ''} onChange={e => update('q', e.target.value)} placeholder={t('search')} />{filters.map(f => <SelectField key={f.key} label={t(f.label || f.key)} value={params[f.key] || ''} onChange={v => update(f.key, v)} options={filterOptions(f.options)} />)}{dateFilters && <><Field label={t('from')} type="date" value={params.from || ''} onChange={e => update('from', e.target.value)} /><Field label={t('to')} type="date" min={params.from} value={params.to || ''} onChange={e => update('to', e.target.value)} /></>}<Button variant="ghost" onClick={clear}>{t('clear')}</Button></div><QueryState query={query}>{result.items.length ? <><div className="pa-table-scroll" tabIndex={0} role="region" aria-label={title}><table><caption className="pa-sr-only">{title}</caption><thead><tr>{columns.map(c => <th key={c.key} scope="col" aria-sort={(params.sort || 'createdAt') === c.key ? params.direction === 'asc' ? 'ascending' : 'descending' : undefined}>{c.sortable === false ? t(c.label || c.key) : <button type="button" onClick={() => table.sortBy(c.key)}>{t(c.label || c.key)}{(params.sort || 'createdAt') === c.key && (params.direction === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />)}</button>}</th>)}{rowAction && <th scope="col">{t('action')}</th>}</tr></thead><tbody>{result.items.map(row => <tr key={row.id}>{columns.map(c => <td key={c.key}>{c.render ? c.render(row) : row[c.key] ?? t('unknown')}</td>)}{rowAction && <td>{rowAction(row)}</td>}</tr>)}</tbody></table></div><footer className="pa-pagination"><span>{t('results', { count: result.total })}</span><SelectField label={t('rows')} value={String(result.pageSize)} onChange={v => update('pageSize', v)} options={[8, 20, 50].map(n => ({ value: String(n), label: n }))} /><div><Button variant="ghost" disabled={result.page <= 1} onClick={() => update('page', String(result.page - 1))} aria-label={t('previous')}><ChevronLeft size={16} /></Button><span>{t('page', { page: result.page, pages })}</span><Button variant="ghost" disabled={result.page >= pages} onClick={() => update('page', String(result.page + 1))} aria-label={t('next')}><ChevronRight size={16} /></Button></div></footer></> : <Empty message={Object.values(params).some(Boolean) ? 'noMatches' : 'empty'} />}</QueryState></section>;
}

