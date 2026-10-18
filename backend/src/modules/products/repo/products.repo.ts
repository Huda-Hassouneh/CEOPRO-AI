import { gtinKey } from "../service/gtin.js";
import { gtinBatchSchema } from "../types/products.validation.js";
import { prisma } from "../../../config/database.js";
import { Prisma } from "../../../generated/prisma/client.js";
import { getFeatureAccessInfo } from "../../features/repo/usage.repo.js";
import { inventoryContext } from "../../forecasting/service/forecasting.policy.js";
import { lockProductCatalog, productCapacity, requireProductCapacity } from "./product-capacity.js";
import { ProductError, type ProductScope } from "../types/products.types.js";
import { requireProductWrite } from "../service/products.permissions.js";
import type { ProductCreate, ProductList, ProductUpdate } from "../types/products.validation.js";

const options = { maxWait: 10_000, timeout: 30_000 };
const names = (value: unknown) => typeof value === "string" ? [value] : value && typeof value === "object" && !Array.isArray(value)
  ? Object.values(value).filter((v): v is string => typeof v === "string") : [];
const normalized = (value: string) => value.trim().toLocaleLowerCase("en-US");
const object = (value: unknown): Record<string, unknown> => value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};

export function retainedImportAliases(metadata: unknown, oldName: unknown, newName: unknown) {
  const previous = object(metadata);
  const aliases = Array.isArray(previous.import_name_aliases) ? previous.import_name_aliases.filter((v): v is string => typeof v === "string") : [];
  if (JSON.stringify(oldName) === JSON.stringify(newName)) return previous as Prisma.InputJsonValue;
  return { ...previous, import_name_aliases: [...new Set([...aliases, ...names(oldName)].map(normalized).filter(Boolean))] } as Prisma.InputJsonValue;
}
function serialize(row: Awaited<ReturnType<Prisma.TransactionClient["products"]["findFirst"]>> & {}) {
  return { id: row.product_id, name: row.product_name, sku: row.sku, gtin: row.gtin ?? null, gtin14: row.gtin ? gtinKey(row.gtin) : null, brand: row.brand, category: row.category,
    description: row.description, price: row.current_price.toString(), costPrice: row.cost_price?.toString() ?? null,
    currency: row.currency, version: row.version, createdAt: row.created_at?.toISOString() ?? null,
    updatedAt: row.updated_at?.toISOString() ?? null, archivedAt: row.deleted_at?.toISOString() ?? null, source: row.source };
}
async function withContext<T>(scope: ProductScope, run: (tx: Prisma.TransactionClient) => Promise<T>) {
  return prisma.$transaction(async (tx) => {
    await tx.$queryRaw`SELECT set_config('app.current_tenant_id', ${scope.tenantId}, true), set_config('app.current_user_id', ${scope.userId}, true)`;
    const access = await getFeatureAccessInfo(scope.tenantId, "product_management", tx);
    if (!access.subscription) throw new ProductError("SUBSCRIPTION_NOT_FOUND");
    if (!access.planFeature) throw new ProductError("FORBIDDEN");
    return run(tx);
  }, options);
}
async function companyCurrencies(tx: Prisma.TransactionClient, tenantId: string) {
  const company = await tx.company.findUnique({ where: { id: tenantId }, select: { primaryCurrency: true, supportedCurrencies: true } });
  const currencies = [...new Set([company?.primaryCurrency, ...(company?.supportedCurrencies ?? [])].filter((v): v is string => !!v).map((v) => v.toUpperCase()))];
  return { currencies, primaryCurrency: company?.primaryCurrency ?? null };
}
async function validateCurrency(tx: Prisma.TransactionClient, tenantId: string, currency: string) {
  const { currencies } = await companyCurrencies(tx, tenantId);
  if (!currencies.includes(currency)) throw new ProductError("INVALID_PARAMETER", { field: "currency", allowed: currencies });
}
async function owned(tx: Prisma.TransactionClient, tenantId: string, id: string, lock = false) {
  if (lock) await tx.$queryRaw`SELECT product_id FROM products WHERE tenant_id = ${tenantId}::uuid AND product_id = ${id}::uuid FOR UPDATE`;
  const row = await tx.products.findFirst({ where: { tenant_id: tenantId, product_id: id } });
  if (!row) throw new ProductError("RESOURCE_NOT_FOUND");
  return row;
}
async function checkIdentity(tx: Prisma.TransactionClient, tenantId: string, name: unknown, sku: string | null, except?: string) {
  const catalog = await tx.products.findMany({ where: { tenant_id: tenantId, deleted_at: null, ...(except ? { product_id: { not: except } } : {}) },
    select: { product_id: true, sku: true, product_name: true, metadata: true } });
  if (sku && catalog.some((row) => row.sku && normalized(row.sku) === normalized(sku))) throw new ProductError("PRODUCT_DUPLICATE", { field: "sku" });
  if (!sku && catalog.some((row) => {
    const aliases = object(row.metadata).import_name_aliases;
    const existing = [...names(row.product_name), ...(Array.isArray(aliases) ? aliases.filter((v): v is string => typeof v === "string") : [])].map(normalized);
    return names(name).some((value) => existing.includes(normalized(value)));
  })) throw new ProductError("PRODUCT_DUPLICATE", { field: "name", requiresSku: true });
}

async function gtinCounts(tx: Prisma.TransactionClient, tenantId: string) {
  const rows = await tx.products.findMany({ where: {tenant_id:tenantId,deleted_at:null},select:{gtin:true} });
  const counts = new Map<string,number>();
  for(const row of rows) if(row.gtin) counts.set(gtinKey(row.gtin),(counts.get(gtinKey(row.gtin)) ?? 0)+1);
  return counts;
}
async function productResult(tx: Prisma.TransactionClient, tenantId: string, row: Parameters<typeof serialize>[0]) {
  const counts=await gtinCounts(tx,tenantId);
  return {...serialize(row),gtinDuplicate:!!row.gtin && (counts.get(gtinKey(row.gtin)) ?? 0)>1};
}

export const productsRepo = {
  previewGtins: (scope: ProductScope, rows: Array<{sku:string;gtin:string}>) => withContext(scope,async tx=>{
    await requireProductWrite(tx,scope);
    const catalog=await tx.products.findMany({where:{tenant_id:scope.tenantId,deleted_at:null}});
    const selected=new Set<string>();
    const preview=rows.map((row,index)=>{
      const matches=catalog.filter(p=>normalized(p.sku ?? '')===normalized(row.sku));
      if(matches.length!==1 || selected.has(matches[0]!.product_id)) throw new ProductError('INVALID_PARAMETER',{reason:'GTIN_IMPORT_PRODUCT',row:index+2});
      const p=matches[0]!;selected.add(p.product_id);
      return {productId:p.product_id,expectedVersion:p.version,name:p.product_name,sku:p.sku,currentGtin:p.gtin,gtin:row.gtin};
    });
    const counts=new Map<string,number>();
    for(const p of catalog){const gtin=preview.find(r=>r.productId===p.product_id)?.gtin ?? p.gtin;if(gtin)counts.set(gtinKey(gtin),(counts.get(gtinKey(gtin)) ?? 0)+1);}
    return {rows:preview.map(row=>({...row,duplicate:(counts.get(gtinKey(row.gtin)) ?? 0)>1}))};
  }),
  applyGtins: (scope: ProductScope, value: unknown) => withContext(scope,async tx=>{
    const parsed=gtinBatchSchema.safeParse(value);
    if(!parsed.success)throw new ProductError('INVALID_PARAMETER');
    await requireProductWrite(tx,scope);await lockProductCatalog(tx,scope.tenantId);
    const ids=parsed.data.rows.map(r=>r.productId);
    if(new Set(ids).size!==ids.length)throw new ProductError('INVALID_PARAMETER');
    const updates=[];
    for(const input of [...parsed.data.rows].sort((a,b)=>a.productId.localeCompare(b.productId))){
      const row=await owned(tx,scope.tenantId,input.productId,true);
      if(row.deleted_at)throw new ProductError('PRODUCT_ARCHIVED');
      if(row.version!==input.expectedVersion)throw new ProductError('PRODUCT_STALE_EDIT');
      if(row.gtin!==input.gtin)updates.push(input);
    }
    for(const input of updates)await tx.products.update({where:{tenant_id_product_id:{tenant_id:scope.tenantId,product_id:input.productId}},data:{gtin:input.gtin,updated_by_user_id:scope.userId}});
    return {updated:updates.length};
  }),
  list: (scope: ProductScope, query: ProductList) => withContext(scope, async (tx) => {
    const term = `%${query.search.replace(/[\\%_]/g, "\\$&")}%`;
    const state = query.status === "active" ? Prisma.sql`p.deleted_at IS NULL` : Prisma.sql`p.deleted_at IS NOT NULL`;
    const filter = Prisma.sql`p.tenant_id = ${scope.tenantId}::uuid AND ${state} AND (
      ${query.search} = '' OR p.product_name ->> 'en' ILIKE ${term} OR p.product_name ->> 'ar' ILIKE ${term}
      OR (CASE WHEN jsonb_typeof(p.product_name) = 'string' THEN p.product_name #>> '{}' ELSE NULL END) ILIKE ${term}
      OR p.sku ILIKE ${term} OR p.gtin ILIKE ${term} OR lpad(p.gtin,14,'0') = ${query.search.padStart(14, '0')})`;
    const sort = query.sort === "name" ? Prisma.sql`COALESCE(NULLIF(p.product_name ->> 'en', ''), p.product_name ->> 'ar', p.product_name #>> '{}') ASC, p.product_id`
      : Prisma.sql`p.created_at DESC NULLS LAST, p.product_id`;
    const counts = await tx.$queryRaw<Array<{ total: bigint }>>`SELECT count(*) AS total FROM products p WHERE ${filter}`;
    const total = Number(counts[0]?.total ?? 0);
    const pages = Math.max(1, Math.ceil(total / query.pageSize)); const page = Math.min(query.page, pages);
    const ids = await tx.$queryRaw<Array<{ product_id: string }>>`SELECT p.product_id FROM products p WHERE ${filter} ORDER BY ${sort} LIMIT ${query.pageSize} OFFSET ${(page - 1) * query.pageSize}`;
    const rows = await tx.products.findMany({ where: { tenant_id: scope.tenantId, product_id: { in: ids.map((row) => row.product_id) } } });
    const gtinTotals=await gtinCounts(tx,scope.tenantId);
    const mapped = new Map(rows.map((row) => [row.product_id, {...serialize(row),gtinDuplicate:!!row.gtin && (gtinTotals.get(gtinKey(row.gtin)) ?? 0)>1}]));
    return { products: ids.map((row) => mapped.get(row.product_id)!), pagination: { page, pageSize: query.pageSize, total, pages },
      capacity: await productCapacity(tx, scope.tenantId), ...await companyCurrencies(tx, scope.tenantId) };
  }),
  get: (scope: ProductScope, id: string) => withContext(scope, async (tx) => {
    const row = await owned(tx, scope.tenantId, id);
    const levels = await tx.inventory.findMany({ where: { tenant_id: scope.tenantId, product_id: id }, orderBy: { warehouse_location: "asc" } });
    const stock = inventoryContext(levels, new Date());
    const history = await tx.product_price_history.findMany({ where: { tenant_id: scope.tenantId, product_id: id }, orderBy: [{ changed_at: "desc" }, { price_history_id: "desc" }], take: 100 });
    return { product: await productResult(tx,scope.tenantId,row), inventory: { currentStock: stock.currentStock, safetyStock: stock.safetyStock, freshness: stock.freshness, reason: stock.reason,
      levels: levels.map((balance) => ({ id: balance.inventory_id, warehouse: balance.warehouse_location, quantity: balance.stock_quantity, reorderLevel: balance.reorder_level, safetyStock: balance.safety_stock, updatedAt: balance.updated_at?.toISOString() ?? null })) },
      priceHistory: history.map((value) => ({ id: value.price_history_id, oldPrice: value.old_price?.toString() ?? null, price: value.new_price.toString(), oldCurrency: value.old_currency, currency: value.currency, changedAt: value.changed_at?.toISOString() ?? null, changedBy: value.changed_by_user_id })),
      ...await companyCurrencies(tx, scope.tenantId) };
  }),
  create: (scope: ProductScope, input: ProductCreate) => withContext(scope, async (tx) => {
    await requireProductWrite(tx, scope);
    await lockProductCatalog(tx, scope.tenantId); await requireProductCapacity(tx, scope.tenantId);
    await validateCurrency(tx, scope.tenantId, input.currency); await checkIdentity(tx, scope.tenantId, input.name, input.sku);
    const row = await tx.products.create({ data: { tenant_id: scope.tenantId, product_name: input.name, sku: input.sku, gtin: input.gtin ?? null, current_price: input.price, cost_price: input.costPrice,
      currency: input.currency, brand: input.brand, category: input.category, description: input.description, source: "MANUAL", created_by_user_id: scope.userId, updated_by_user_id: scope.userId } });
    // Product writes no longer enqueue the withdrawn competitor discovery bridge.
    return { product: await productResult(tx,scope.tenantId,row) };
  }),
  update: (scope: ProductScope, id: string, input: ProductUpdate) => withContext(scope, async (tx) => {
    await requireProductWrite(tx, scope);
    await lockProductCatalog(tx, scope.tenantId); const current = await owned(tx, scope.tenantId, id, true);
    if (current.deleted_at) throw new ProductError("PRODUCT_ARCHIVED");
    if (current.version !== input.expectedVersion) throw new ProductError("PRODUCT_STALE_EDIT");
    if (input.currency) await validateCurrency(tx, scope.tenantId, input.currency);
    if ((input.name && JSON.stringify(input.name) !== JSON.stringify(current.product_name)) ||
        ("sku" in input && normalized(input.sku ?? "") !== normalized(current.sku ?? "")))
      await checkIdentity(tx, scope.tenantId, input.name ?? current.product_name, "sku" in input ? input.sku! : current.sku, id);
    const data: Prisma.productsUncheckedUpdateInput = { updated_by_user_id: scope.userId };
    if (input.name) { data.product_name = input.name; data.metadata = retainedImportAliases(current.metadata, current.product_name, input.name); }
    if ("sku" in input) data.sku = input.sku;
    if (input.gtin !== undefined) data.gtin = input.gtin;
    if (input.price !== undefined) data.current_price = input.price;
    if (input.costPrice !== undefined) data.cost_price = input.costPrice;
    if (input.currency) data.currency = input.currency;
    for (const field of ["brand", "category", "description"] as const) if (input[field]) data[field] = input[field];
    const row = await tx.products.update({ where: { tenant_id_product_id: { tenant_id: scope.tenantId, product_id: id } }, data });
    return { product: await productResult(tx,scope.tenantId,row) };
  }),
  archive: (scope: ProductScope, id: string, version: number, restore = false) => withContext(scope, async (tx) => {
    await requireProductWrite(tx, scope);
    await lockProductCatalog(tx, scope.tenantId); const current = await owned(tx, scope.tenantId, id, true);
    if (current.version !== version) throw new ProductError("PRODUCT_STALE_EDIT");
    if (Boolean(current.deleted_at) === !restore) return { product: await productResult(tx,scope.tenantId,current) };
    if (restore) { await requireProductCapacity(tx, scope.tenantId); await checkIdentity(tx, scope.tenantId, current.product_name, current.sku, id); }
    const row = await tx.products.update({ where: { tenant_id_product_id: { tenant_id: scope.tenantId, product_id: id } }, data: { deleted_at: restore ? null : new Date(), updated_by_user_id: scope.userId } });
    return { product: await productResult(tx,scope.tenantId,row) };
  })
};
