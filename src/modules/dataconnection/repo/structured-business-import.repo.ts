import { createHash } from "node:crypto";
import { prisma } from "../../../config/database.js";
import type { Prisma } from "../../../generated/prisma/client.js";
import {
  FeatureUsageCapacityError,
  FeatureUsageUnavailableError,
  getFeatureAccessInfo,
  reserveFeatureUsageInTransaction
} from "../../features/repo/usage.repo.js";
import { safeUploadName } from "../types/dataconnection.validation.js";
import {
  StructuredImportError,
  normalizeProductReference,
  parseStructuredBusinessFile,
  type StructuredImportKind,
  type ParsedBusinessImport
} from "../service/structured-business-import.js";
import {
  matchImportProducts,
  productRowKey,
  productRows,
  type CatalogProduct,
  type ProductMatch
} from "../service/business-product-matching.js";

type Transaction = Prisma.TransactionClient;
export type Choice = { action: "select"; productId: string } | { action: "create"; price: string; currency: string; sku?: string };
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

async function setTenant(tx: Transaction, tenantId: string, userId: string) {
  await tx.$queryRaw`
    SELECT set_config('app.current_tenant_id', ${tenantId}, true),
           set_config('app.current_user_id', ${userId}, true)
  `;
}

async function activeProducts(tx: Transaction, tenantId: string): Promise<CatalogProduct[]> {
  return tx.products.findMany({
    where: { tenant_id: tenantId, deleted_at: null },
    select: { product_id: true, product_name: true, sku: true, currency: true,
      current_price: true, brand: true, category: true, created_at: true }
  });
}

async function calculateReview(tx: Transaction, tenantId: string, parsed: ParsedBusinessImport,
  choices: Record<string, Choice>, sha256: string) {
  const catalog = await activeProducts(tx, tenantId);
  const matches = matchImportProducts(parsed, catalog);
  const company = await tx.company.findUnique({ where: { id: tenantId }, select: { primaryCurrency: true, supportedCurrencies: true } });
  if (!company) throw new StructuredImportError("The company is unavailable.");
  if (Object.values(choices).some((choice) => choice.action === "create")) {
    const access = await getFeatureAccessInfo(tenantId, "product_management", tx);
    if (!access.subscription || !access.planFeature) {
      throw new FeatureUsageUnavailableError();
    }
  }
  const validKeys = new Set(matches.map((match) => match.key));
  if (Object.keys(choices).some((key) => !validKeys.has(key))) throw new StructuredImportError("Invalid product choices.");
  const assignments = new Map<string, string | null>();
  const proposedProducts = new Map<string, { price: number; currency: string; name: string }>();
  for (const row of productRows(parsed)) {
    const key = productRowKey(row);
    const match = matches.find((entry) => entry.key === key)!;
    const choice = choices[key];
    if (match.status === "conflict") throw new StructuredImportError(match.message!, [{ sheet: row.sheet, row: row.row, message: match.message! }]);
    if (match.status === "matched") {
      if (choice) throw new StructuredImportError("The catalog changed since preview. Review the file again.");
      assignments.set(key, match.productId);
    } else if (choice?.action === "select") {
      if (!catalog.some((product) => product.product_id === choice.productId) ||
        match.status === "ambiguous" && !match.candidates.some((product) => product.product_id === choice.productId)) {
        throw new StructuredImportError("Select an active product owned by this company.", [{ sheet: row.sheet, row: row.row, message: "Invalid product selection." }]);
      }
      assignments.set(key, choice.productId);
    } else if (choice?.action === "create" && match.status === "missing" && row.productName) {
      const currency = choice.currency?.toUpperCase();
      const sku = choice.sku?.trim() || row.sku;
      if (!/^(?:0|[1-9]\d{0,7})(?:\.\d{1,4})?$/.test(choice.price) ||
        ![company.primaryCurrency, ...company.supportedCurrencies].some((allowed) => allowed.toUpperCase() === currency) ||
        (sku && !/^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/.test(sku)) ||
        row.sku && normalizeProductReference(sku) !== normalizeProductReference(row.sku)) {
        throw new StructuredImportError("Check the new product's price, currency, and SKU.", [{ sheet: row.sheet, row: row.row, message: "Invalid product details." }]);
      }
      const identity = sku ? `sku:${normalizeProductReference(sku)}` : `name:${normalizeProductReference(row.productName)}`;
      const previous = proposedProducts.get(identity);
      if (previous && (previous.price !== Number(choice.price) || previous.currency !== currency || previous.name !== normalizeProductReference(row.productName))) {
        throw new StructuredImportError("Rows creating the same product must use the same name, price, and currency.", [{ sheet: row.sheet, row: row.row, message: "Conflicting new product details." }]);
      }
      proposedProducts.set(identity, { price: Number(choice.price), currency, name: normalizeProductReference(row.productName) });
      assignments.set(key, null);
    } else {
      throw new StructuredImportError(match.message ?? "Resolve this product before continuing.", [{ sheet: row.sheet, row: row.row, message: match.message ?? "Resolve this product before continuing." }]);
    }
  }
  const inventory = parsed.kind === "inventory" ? await tx.inventory.findMany({
    where: { tenant_id: tenantId, product_id: { in: [...assignments.values()].filter((id): id is string => !!id) } },
    select: { product_id: true, warehouse_location: true, stock_quantity: true }
  }) : [];
  const changes = parsed.kind === "inventory" ? parsed.inventory.map((row) => {
    const key = productRowKey(row);
    const id = assignments.get(key);
    const previous = id ? inventory.find((balance) => inventoryKey(balance.product_id, balance.warehouse_location) === inventoryKey(id, row.warehouseLocation)) : null;
    return { key, productName: row.productName || catalog.find((product) => product.product_id === id)?.product_name || "",
      warehouse: row.warehouseLocation, previous: previous?.stock_quantity ?? null,
      next: row.stockQuantity, operation: previous ? "replace" : "create" };
  }) : [];
  const unique = new Set<string>();
  for (const row of productRows(parsed)) {
    const id = assignments.get(productRowKey(row));
    const choice = choices[productRowKey(row)];
    const identity = id ?? `new:${choice?.action === "create" && choice.sku ? normalizeProductReference(choice.sku) : normalizeProductReference(row.productName)}`;
    const key = parsed.kind === "inventory" && "warehouseLocation" in row
      ? `${identity}:${normalizeProductReference(row.warehouseLocation ?? "")}`
      : `${"invoiceNumber" in row ? row.invoiceNumber.toLowerCase() : ""}:${identity}`;
    if (unique.has(key)) throw new StructuredImportError("Two rows resolve to the same product and invoice or warehouse.", [{ sheet: row.sheet, row: row.row, message: "Duplicate product after matching." }]);
    unique.add(key);
  }
  const hash = createHash("sha256").update(JSON.stringify({ sha256, choices: Object.entries(choices).sort(),
    assignments: [...assignments.entries()], changes })).digest("hex");
  return { reviewHash: hash, changes, counts: {
    invoices: parsed.kind === "invoices" ? parsed.invoices.length : 0,
    items: parsed.kind === "invoices" ? parsed.items.length : 0,
    inventory: parsed.kind === "inventory" ? parsed.inventory.length : 0,
    productsToCreate: new Set(productRows(parsed).filter((row) => choices[productRowKey(row)]?.action === "create")
      .map((row) => {
        const choice = choices[productRowKey(row)] as Extract<Choice, { action: "create" }>;
        return choice.sku ? `sku:${normalizeProductReference(choice.sku)}` : `name:${normalizeProductReference(row.productName)}`;
      })).size
  } };
}

export async function reviewBusinessImport(input: { tenantId: string; userId: string; kind: StructuredImportKind;
  draftId: string; choices: Record<string, Choice> }) {
  return prisma.$transaction(async (tx) => {
    await setTenant(tx, input.tenantId, input.userId);
    const draft = await tx.business_import_drafts.findFirst({ where: {
      draft_id: input.draftId, tenant_id: input.tenantId, user_id: input.userId, kind: input.kind, status: "PREVIEW"
    } });
    if (!draft?.file_bytes || draft.expires_at < new Date()) throw new StructuredImportError("This preview expired. Upload the file again.");
    const fileBuffer = Buffer.from(draft.file_bytes);
    if (createHash("sha256").update(fileBuffer).digest("hex") !== draft.sha256) {
      throw new StructuredImportError("The saved preview is invalid. Upload the file again.");
    }
    const parsed = parseStructuredBusinessFile(input.kind, { originalname: draft.file_name, size: fileBuffer.length, buffer: fileBuffer });
    return calculateReview(tx, input.tenantId, parsed, input.choices, draft.sha256);
  }, { maxWait: 10_000, timeout: 30_000 });
}

export async function searchStructuredImportProducts(tenantId: string, userId: string, query: string) {
  return prisma.$transaction(async (tx) => {
    await setTenant(tx, tenantId, userId);
    const products = await activeProducts(tx, tenantId);
    const needle = normalizeProductReference(query).slice(0, 100);
    return products.filter((product) => !needle || normalizeProductReference(product.sku ?? "").includes(needle) ||
      Object.values(product.product_name && typeof product.product_name === "object" && !Array.isArray(product.product_name)
        ? product.product_name : { en: product.product_name })
        .some((name) => typeof name === "string" && normalizeProductReference(name).includes(needle)))
      .slice(0, 50);
  });
}

export async function createBusinessImportPreview(input: {
  tenantId: string; userId: string; fileName: string; fileBuffer: Buffer; parsed: ParsedBusinessImport;
}) {
  return prisma.$transaction(async (tx) => {
    await setTenant(tx, input.tenantId, input.userId);
    await tx.business_import_drafts.deleteMany({ where: {
      tenant_id: input.tenantId, user_id: input.userId,
      OR: [
        { status: "PREVIEW", expires_at: { lt: new Date() } },
        { status: "COMPLETED", expires_at: { lt: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000) } }
      ]
    } });
    const company = await tx.company.findUnique({ where: { id: input.tenantId }, select: { primaryCurrency: true, supportedCurrencies: true } });
    if (!company) throw new StructuredImportError("The company is unavailable.");
    const productManagement = await getFeatureAccessInfo(input.tenantId, "product_management", tx);
    const matches = matchImportProducts(input.parsed, await activeProducts(tx, input.tenantId));
    const invoiceNumbers = input.parsed.kind === "invoices" ? input.parsed.invoices.map((row) => row.invoiceNumber) : [];
    const duplicateInvoices = invoiceNumbers.length ? await tx.invoices.findMany({
      where: { tenant_id: input.tenantId, invoice_number: { in: invoiceNumbers, mode: "insensitive" } },
      select: { invoice_number: true }
    }) : [];
    const inventory = input.parsed.kind === "inventory" ? await tx.inventory.findMany({
      where: { tenant_id: input.tenantId, product_id: { in: matches.flatMap((match) => match.productId ? [match.productId] : []) } },
      select: { product_id: true, warehouse_location: true, stock_quantity: true }
    }) : [];
    const changes = input.parsed.kind === "inventory" ? input.parsed.inventory.map((row) => {
      const productId = matches.find((match) => match.key === productRowKey(row))?.productId;
      const old = inventory.find((balance) => balance.product_id === productId && inventoryKey(balance.product_id, balance.warehouse_location) === inventoryKey(balance.product_id, row.warehouseLocation));
      return { key: productRowKey(row), previous: old?.stock_quantity ?? null, next: row.stockQuantity, operation: old ? "replace" : "create" };
    }) : [];
    const draft = await tx.business_import_drafts.create({ data: {
      tenant_id: input.tenantId, user_id: input.userId, kind: input.parsed.kind,
      file_name: safeUploadName(input.fileName).slice(0, 255),
      file_bytes: Uint8Array.from(input.fileBuffer),
      sha256: createHash("sha256").update(input.fileBuffer).digest("hex"),
      expires_at: new Date(Date.now() + 60 * 60 * 1000)
    }, select: { draft_id: true, expires_at: true } });
    return {
      draftId: draft.draft_id, kind: input.parsed.kind, expiresAt: draft.expires_at,
      sheets: input.parsed.kind === "invoices" ? (input.parsed.items.length ? ["Invoices", "Invoice Items"] : ["Invoices"]) : ["Inventory"],
      counts: { invoices: invoiceNumbers.length, items: input.parsed.kind === "invoices" ? input.parsed.items.length : 0,
        inventory: input.parsed.kind === "inventory" ? input.parsed.inventory.length : 0,
        matched: matches.filter((match) => match.status === "matched").length,
        needsAttention: matches.filter((match) => match.status !== "matched").length },
      matches, changes,
      issues: [
        ...duplicateInvoices.map((existing) => ({ sheet: "Invoices", row: input.parsed.kind === "invoices"
          ? input.parsed.invoices.find((invoice) => invoice.invoiceNumber.toLowerCase() === existing.invoice_number.toLowerCase())?.row ?? 0 : 0,
          message: `Invoice ${existing.invoice_number} already exists.` })),
        ...(input.parsed.kind === "invoices" ? input.parsed.invoices.filter((invoice) =>
          ![company.primaryCurrency, ...company.supportedCurrencies].some((currency) => currency.toUpperCase() === invoice.currency))
          .map((invoice) => ({ sheet: "Invoices", row: invoice.row, message: `Currency ${invoice.currency} is not configured for this company.` })) : [])
      ],
      primaryCurrency: company.primaryCurrency,
      canCreateProducts: Boolean(productManagement.subscription && productManagement.planFeature)
    };
  }, { maxWait: 10_000, timeout: 30_000 });
}

export async function confirmBusinessImport(input: {
  tenantId: string; userId: string; draftId: string; kind: StructuredImportKind;
  choices: Record<string, Choice>; reviewHash: string;
}) {
  return persistStructuredBusinessImport({
    tenantId: input.tenantId, userId: input.userId, draftId: input.draftId,
    fileName: "", fileBuffer: Buffer.alloc(0),
    parsed: input.kind === "invoices" ? { kind: "invoices", invoices: [], items: [] } : { kind: "inventory", inventory: [] },
    choices: input.choices, reviewHash: input.reviewHash
  });
}

export class DuplicateStructuredImportError extends Error {
  constructor() {
    super("An invoice number from this file already exists for this company. No rows were imported.");
    this.name = "DuplicateStructuredImportError";
  }
}

function inventoryKey(productId: string, warehouseLocation: string | null) {
  return `${productId}:${warehouseLocation?.trim().toLowerCase() ?? ""}`;
}

/** Product identifiers for a tenant's invoice-item and inventory templates. */
export async function getStructuredImportProductReference(tenantId: string, userId: string) {
  return prisma.$transaction(async (tx) => {
    await tx.$queryRaw`
      SELECT set_config('app.current_tenant_id', ${tenantId}, true),
             set_config('app.current_user_id', ${userId}, true)
    `;
    return tx.products.findMany({
      where: { tenant_id: tenantId, deleted_at: null },
      select: { product_id: true, product_name: true, sku: true, currency: true },
      orderBy: { product_id: "asc" }
    });
  });
}

/** A file is either fully committed with its usage charge and job, or fully rolled back. */
export async function persistStructuredBusinessImport(input: {
  tenantId: string;
  userId: string;
  fileName: string;
  fileBuffer: Buffer;
  parsed: ParsedBusinessImport;
  draftId?: string;
  choices?: Record<string, Choice>;
  reviewHash?: string;
}) {
  const { tenantId, userId } = input;
  try {
    return await prisma.$transaction(async (tx) => {
      await setTenant(tx, tenantId, userId);
      // inventory has no product/warehouse unique key. Serialize its read/update/create
      // with all other structured imports for this tenant to prevent duplicate balances.
      await tx.$executeRawUnsafe(
        "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
        `business-import:${tenantId}`
      );
      let parsed = input.parsed;
      let fileBuffer = input.fileBuffer;
      let fileName = input.fileName;
      if (input.draftId) {
        if (!UUID.test(input.draftId)) throw new StructuredImportError("Invalid preview identifier.");
        // Lock the draft before charging usage or creating records. A second
        // confirmation waits, then returns the first committed result.
        await tx.$queryRaw`SELECT draft_id FROM business_import_drafts
          WHERE draft_id = ${input.draftId}::uuid AND tenant_id = ${tenantId}::uuid
          AND user_id = ${userId}::uuid FOR UPDATE`;
        const draft = await tx.business_import_drafts.findFirst({
          where: { draft_id: input.draftId, tenant_id: tenantId, user_id: userId }
        });
        if (!draft) throw new StructuredImportError("The preview is unavailable for this user and company.");
        if (draft.kind !== input.parsed.kind) throw new StructuredImportError("The preview has a different import type.");
        if (draft.status === "COMPLETED" && draft.result && typeof draft.result === "object") return draft.result as unknown as {
          jobId: string; kind: StructuredImportKind; imported: number; updated: number; invoiceItems: number; chargedKb: number;
        };
        if (draft.expires_at < new Date() || !draft.file_bytes) {
          throw new StructuredImportError("This preview expired. Upload the file again.");
        }
        const storedBytes = Buffer.from(draft.file_bytes);
        if (createHash("sha256").update(storedBytes).digest("hex") !== draft.sha256) {
          throw new StructuredImportError("The saved preview is invalid. Upload the file again.");
        }
        parsed = parseStructuredBusinessFile(draft.kind as StructuredImportKind, {
          originalname: draft.file_name, size: storedBytes.length, buffer: storedBytes
        });
        fileBuffer = storedBytes;
        fileName = draft.file_name;
      }
      const chargedKb = Math.max(1, Math.ceil(fileBuffer.length / 1024));
      const company = await tx.company.findUnique({
        where: { id: tenantId },
        select: { primaryCurrency: true, supportedCurrencies: true }
      });
      if (!company) throw new StructuredImportError("The company is unavailable.");
      if (input.draftId) {
        const review = await calculateReview(tx, tenantId, parsed, input.choices ?? {}, createHash("sha256").update(fileBuffer).digest("hex"));
        if (review.reviewHash !== input.reviewHash) {
          throw new StructuredImportError("The inventory or product catalog changed since review. Review the changes again.");
        }
      }

      // Resolve references again at commit: products can be changed or deleted
      // after preview. The client supplies choices only; all values are checked
      // against the authenticated tenant's current catalog.
      const catalog = await activeProducts(tx, tenantId);
      const matches = matchImportProducts(parsed, catalog);
      const choices = input.choices ?? {};
      const validKeys = new Set(matches.map((match) => match.key));
      if (Object.keys(choices).some((key) => !validKeys.has(key))) {
        throw new StructuredImportError("The product choices do not belong to this preview.");
      }
      const newlyCreated = new Map<string, { id: string; price: string; currency: string; name: string }>();
      for (const row of productRows(parsed)) {
        const key = productRowKey(row);
        const match = matches.find((item) => item.key === key)!;
        const choice = choices[key];
        if (match.status === "conflict") throw new StructuredImportError(match.message!, [{ sheet: row.sheet, row: row.row, message: match.message! }]);
        if (match.status === "matched") {
          if (choice) throw new StructuredImportError("The catalog changed since preview. Review the file again.", [{ sheet: row.sheet, row: row.row, message: "The catalog changed since preview." }]);
          row.productId = match.productId!;
          continue;
        }
        if (!choice) throw new StructuredImportError(match.message!, [{ sheet: row.sheet, row: row.row, message: match.message! }]);
        if (choice.action === "select") {
          const selected = catalog.find((product) => product.product_id === choice.productId);
          if (!selected || match.status === "ambiguous" && !match.candidates.some((candidate) => candidate.product_id === selected.product_id)) {
            throw new StructuredImportError("Select an active product belonging to this company.", [{ sheet: row.sheet, row: row.row, message: "Invalid product selection." }]);
          }
          row.productId = selected.product_id;
          continue;
        }
        if (choice.action !== "create" || match.status !== "missing" || !row.productName) {
          throw new StructuredImportError("Provide a product name before creating a new product.", [{ sheet: row.sheet, row: row.row, message: "Provide a product name before creating a new product." }]);
        }
        const price = choice.price;
        const currency = choice.currency?.toUpperCase();
        const sku = choice.sku?.trim() || row.sku || null;
        if (!/^(?:0|[1-9]\d{0,7})(?:\.\d{1,4})?$/.test(price) ||
          ![company.primaryCurrency, ...company.supportedCurrencies].some((allowed) => allowed.toUpperCase() === currency) ||
          (sku !== null && (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/.test(sku) || row.sku && normalizeProductReference(sku) !== normalizeProductReference(row.sku)))) {
          throw new StructuredImportError("Check the new product's price, currency, and SKU.", [{ sheet: row.sheet, row: row.row, message: "Invalid product details." }]);
        }
        const identity = sku ? `sku:${normalizeProductReference(sku)}` : `name:${normalizeProductReference(row.productName)}`;
        const existingProduct = newlyCreated.get(identity);
        if (existingProduct) {
          if (Number(existingProduct.price) !== Number(price) || existingProduct.currency !== currency ||
            normalizeProductReference(existingProduct.name) !== normalizeProductReference(row.productName)) {
            throw new StructuredImportError("Rows creating the same product must use the same name, price, and currency.", [{ sheet: row.sheet, row: row.row, message: "Conflicting new product details." }]);
          }
          row.productId = existingProduct.id;
          continue;
        }
        const created = await tx.products.create({ data: {
          tenant_id: tenantId, product_name: { en: row.productName, ar: row.productName },
          sku, current_price: price, currency, created_by_user_id: userId, source: "MANUAL"
        }, select: { product_id: true } });
        row.productId = created.product_id;
        newlyCreated.set(identity, { id: created.product_id, price, currency, name: row.productName });
      }
      const deduped = new Set<string>();
      for (const row of parsed.kind === "inventory" ? parsed.inventory : parsed.items) {
        const key = parsed.kind === "inventory"
          ? inventoryKey(row.productId, "warehouseLocation" in row ? row.warehouseLocation : null)
          : `${"invoiceNumber" in row ? row.invoiceNumber.toLowerCase() : ""}:${row.productId}`;
        if (deduped.has(key)) throw new StructuredImportError("Two rows resolve to the same product and invoice or warehouse.", [{ sheet: row.sheet, row: row.row, message: "Duplicate product after matching." }]);
        deduped.add(key);
      }

      let imported = 0;
      let updated = 0;
      let itemCount = 0;
      if (parsed.kind === "invoices") {
        const allowedCurrencies = new Set([
          company.primaryCurrency.toUpperCase(),
          ...company.supportedCurrencies.map((currency) => currency.toUpperCase())
        ]);
        const unsupported = parsed.invoices.find((invoice) => !allowedCurrencies.has(invoice.currency));
        if (unsupported) {
          throw new StructuredImportError(`Currency ${unsupported.currency} is not configured for this company.`);
        }
        const invoiceNumbers = parsed.invoices.map((invoice) => invoice.invoiceNumber);
        const existing = await tx.invoices.findFirst({
          where: { tenant_id: tenantId, invoice_number: { in: invoiceNumbers, mode: "insensitive" } },
          select: { invoice_id: true }
        });
        if (existing) throw new DuplicateStructuredImportError();
        if (parsed.items.length) {
          const requested = [...new Set(parsed.items.map((item) => item.productId))];
          const products = await tx.products.findMany({
            where: { tenant_id: tenantId, deleted_at: null, product_id: { in: requested } },
            select: { product_id: true }
          });
          if (products.length !== requested.length) {
            throw new StructuredImportError("Every invoice item must refer to an active product owned by this company.");
          }
        }
        // The reservation shares this transaction with the business records.
        await reserveFeatureUsageInTransaction(tx, tenantId, "document_extraction", chargedKb);
        const inserted = await tx.invoices.createManyAndReturn({
          data: parsed.invoices.map((invoice) => ({
            tenant_id: tenantId,
            invoice_number: invoice.invoiceNumber,
            customer_name: invoice.customerName,
            issue_date: invoice.issueDate,
            due_date: invoice.dueDate,
            subtotal: invoice.subtotal,
            tax_amount: invoice.taxAmount,
            total_amount: invoice.totalAmount,
            currency: invoice.currency,
            payment_status: invoice.paymentStatus,
            created_by_user_id: userId
          })),
          select: { invoice_id: true, invoice_number: true }
        });
        const ids = new Map(inserted.map((invoice) => [invoice.invoice_number.toLowerCase(), invoice.invoice_id]));
        if (parsed.items.length) {
          await tx.invoice_items.createMany({
            data: parsed.items.map((item) => ({
              tenant_id: tenantId,
              invoice_id: ids.get(item.invoiceNumber.toLowerCase())!,
              product_id: item.productId,
              quantity: item.quantity,
              unit_price: item.unitPrice,
              total_price: item.totalPrice
            }))
          });
        }
        const savedInvoices = await tx.invoices.count({ where: {
          tenant_id: tenantId, invoice_id: { in: inserted.map((invoice) => invoice.invoice_id) }
        } });
        const savedItems = await tx.invoice_items.count({ where: {
          tenant_id: tenantId, invoice_id: { in: inserted.map((invoice) => invoice.invoice_id) }
        } });
        if (savedInvoices !== inserted.length || savedItems !== parsed.items.length) {
          throw new StructuredImportError("Invoice persistence verification failed; the transaction was rolled back.");
        }
        imported = inserted.length;
        itemCount = parsed.items.length;
      } else {
        const requested = [...new Set(parsed.inventory.map((row) => row.productId))];
        const products = await tx.products.findMany({
          where: { tenant_id: tenantId, deleted_at: null, product_id: { in: requested } },
          select: { product_id: true }
        });
        if (products.length !== requested.length) {
          throw new StructuredImportError("Every inventory row must refer to an active product owned by this company.");
        }
        const existing = await tx.inventory.findMany({
          where: { tenant_id: tenantId, product_id: { in: requested } },
          select: { inventory_id: true, product_id: true, warehouse_location: true }
        });
        const balances = new Map<string, string>();
        for (const balance of existing) {
          const key = inventoryKey(balance.product_id, balance.warehouse_location);
          if (balances.has(key)) {
            throw new StructuredImportError("Duplicate inventory balances already exist for a product and warehouse. Resolve them before importing.");
          }
          balances.set(key, balance.inventory_id);
        }
        await reserveFeatureUsageInTransaction(tx, tenantId, "document_extraction", chargedKb);
        for (const row of parsed.inventory) {
          const data = {
            stock_quantity: row.stockQuantity,
            reorder_level: row.reorderLevel,
            safety_stock: row.safetyStock,
            warehouse_location: row.warehouseLocation
          };
          const id = balances.get(inventoryKey(row.productId, row.warehouseLocation));
          if (id) {
            await tx.inventory.update({ where: { inventory_id: id, tenant_id: tenantId }, data: { ...data, updated_at: new Date() } });
            updated += 1;
          } else {
            await tx.inventory.create({ data: { tenant_id: tenantId, product_id: row.productId, ...data } });
            imported += 1;
          }
        }
        const savedBalances = await tx.inventory.findMany({ where: {
          tenant_id: tenantId, product_id: { in: requested }
        }, select: { product_id: true, warehouse_location: true, stock_quantity: true, reorder_level: true, safety_stock: true } });
        if (parsed.inventory.some((row) => {
          const actual = savedBalances.filter((balance) => inventoryKey(balance.product_id, balance.warehouse_location) === inventoryKey(row.productId, row.warehouseLocation));
          return actual.length !== 1 || actual[0]!.stock_quantity !== row.stockQuantity ||
            actual[0]!.reorder_level !== row.reorderLevel || actual[0]!.safety_stock !== row.safetyStock;
        })) {
          throw new StructuredImportError("Inventory persistence verification failed; the transaction was rolled back.");
        }
      }
      const now = new Date();
      const source = await tx.data_sources.create({
        data: {
          tenant_id: tenantId,
          source_type: "documents",
          source_name: safeUploadName(fileName).slice(0, 100),
          is_active: false,
          collector_config: {
            import_kind: parsed.kind,
            content_sha256: createHash("sha256").update(fileBuffer).digest("hex")
          }
        },
        select: { source_id: true }
      });
      const job = await tx.ingestion_jobs.create({
        data: {
          tenant_id: tenantId,
          source_id: source.source_id,
          job_status: "COMPLETED",
          rows_processed: imported + updated + itemCount,
          rows_failed: 0,
          started_at: now,
          ended_at: now
        },
        select: { job_id: true }
      });
      const result = { jobId: job.job_id, kind: parsed.kind, imported, updated, invoiceItems: itemCount, chargedKb };
      if (input.draftId) {
        await tx.business_import_drafts.update({ where: { draft_id: input.draftId }, data: { status: "COMPLETED", file_bytes: null, result } });
      }
      return result;
    }, { maxWait: 10_000, timeout: 120_000 });
  } catch (error) {
    if (error instanceof FeatureUsageUnavailableError || error instanceof FeatureUsageCapacityError || error instanceof StructuredImportError || error instanceof DuplicateStructuredImportError) throw error;
    if (error && typeof error === "object" && "code" in error && error.code === "P2002") {
      throw new StructuredImportError("An invoice number or SKU already exists. Refresh the preview before confirming.");
    }
    throw error;
  }
}
