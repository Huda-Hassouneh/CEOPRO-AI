import { useState } from 'react';
import { Package, Plus, Search, Layers, Archive } from 'lucide-react';
import PageHeader from '../../../shared/components/layout/PageHeader.jsx';
import Card from '../../../shared/components/ui/Card.jsx';
import Input from '../../../shared/components/ui/Input.jsx';
import Select from '../../../shared/components/ui/Select.jsx';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import RecordSummary from '../../../shared/components/ui/RecordSummary.jsx';
import { CatalogTable } from '../components/CatalogTable.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { useAuthStore } from '../../auth/store/authStore.js';
import BusinessPageContainer from '../../../shared/components/layout/BusinessPageContainer.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import Modal from '../../../shared/components/ui/Modal.jsx';
import { getApiErrorMessage } from '../../../shared/lib/apiErrorCore.js';
import { useCatalog, useCatalogMutation } from '../hooks/useCatalog.js';
import { GtinImport } from '../components/GtinImport.jsx';
import { ProductForm } from '../components/ProductForm.jsx';
import '../catalog.css';
export { productText } from '../utils/productText.js';
export function CatalogPage() {
  const tenant = useAuthStore((state) => state.tenantId);
  return <Catalog key={tenant} />;
}
function Catalog() {
  const { t, locale } = useI18n();
  const [search, setSearch] = useState(''); const [status, setStatus] = useState('active'); const [sort, setSort] = useState('name'); const [page, setPage] = useState(1); const [creating, setCreating] = useState(false);
  const query = useCatalog({ search, status, sort, page, pageSize: 25 }); const create = useCatalogMutation('create'); const data = query.data;
  const close = () => { if (!create.isPending) { setCreating(false); create.reset(); } };
  return <BusinessPageContainer className="catalog-page">
    <PageHeader title={t('catalog.title')} subtitle={t('catalog.subtitle')} actions={data?.canEdit && <Button leadingIcon={<Plus size={17} />} disabled={query.isFetching || (!data.capacity?.isUnlimited && data.capacity?.remaining === 0)} onClick={() => setCreating(true)}>{t('catalog.add')}</Button>} />
    {!query.isError && <RecordSummary items={[
      {label:t('catalog.ux.catalogUsage'),value:data?.capacity?.currentUsage,icon:<Package size={21} />,hint:data?.capacity ? t(data.capacity.isUnlimited ? 'catalog.capacityUnlimited' : 'catalog.capacity',{used:data.capacity.currentUsage,limit:data.capacity.limit}) : undefined},
      {label:t('catalog.ux.matchingProducts'),value:data?.pagination?.total,icon:<Layers size={21} />,hint:t('catalog.ux.matchingHint')},
      {label:t('catalog.status'),value:t(status==='active'?'catalog.active':'catalog.archived'),icon:<Archive size={21} />,hint:t('catalog.ux.statusHint')}
    ]} />}
    <Card className="catalog-directory">
    <div className="catalog-toolbar">
      <Input label={t('catalog.search')} type="search" maxLength={150} placeholder={t('catalog.ux.searchHint')} leftIcon={<Search size={17} />} value={search} onChange={e=>{setSearch(e.target.value);setPage(1);}} />
      <Select label={t('catalog.status')} value={status} onChange={e=>{setStatus(e.target.value);setPage(1);}} options={['active','archived'].map(value=>({value,label:t(`catalog.${value}`)}))} />
      <Select label={t('catalog.sort')} value={sort} onChange={e=>{setSort(e.target.value);setPage(1);}} options={[{value:'name',label:t('catalog.byName')},{value:'newest',label:t('catalog.newest')}]} />
    </div>
    {search && <div className="catalog-filter-feedback"><span>{t('catalog.ux.searchingFor')} <strong><bdi>{search}</bdi></strong></span><Button variant="ghost" size="sm" onClick={()=>{setSearch('');setPage(1);}}>{t('catalog.ux.clearSearch')}</Button></div>}
    {query.isPending && <div role="status" aria-label={t('catalog.loading')}><Skeleton height="240px" variant="rectangular" /></div>}
    {query.isError && <div role="alert" className="catalog-error"><p>{getApiErrorMessage(query.error, t)}</p><Button onClick={() => query.refetch()}>{t('catalog.retry')}</Button></div>}
    {data && !query.isError && <>
      <CatalogTable products={data.products} t={t} locale={locale} filtered={Boolean(search)} emptyAction={search ? <Button variant="outline" onClick={()=>{setSearch('');setPage(1);}}>{t('catalog.ux.clearSearch')}</Button> : undefined} />
      <div className="catalog-pagination"><Button variant="outline" disabled={query.isFetching || data.pagination.page <= 1} onClick={() => setPage(data.pagination.page - 1)}>{t('catalog.previous')}</Button><span>{t('catalog.pagination', data.pagination)}</span><Button variant="outline" disabled={query.isFetching || data.pagination.page >= data.pagination.pages} onClick={() => setPage(data.pagination.page + 1)}>{t('catalog.next')}</Button></div>
    </>}
    </Card>
    {data?.canEdit && <GtinImport t={t} locale={locale} />}
    <Modal isOpen={creating && Boolean(data?.canEdit)} title={t('catalog.add')} closeLabel={t('catalog.cancel')} onClose={close} maxWidth="720px">
      {creating && data && <ProductForm t={t} currencies={data.currencies} primaryCurrency={data.primaryCurrency} pending={create.isPending} error={create.isError ? getApiErrorMessage(create.error, t) : null} onCancel={close} onSubmit={(input) => create.mutate(input, { onSuccess: () => setCreating(false) })} />}
    </Modal>
  </BusinessPageContainer>;
}
