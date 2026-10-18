import { z } from "zod";
import { validGtin } from "../service/gtin.js";
export const gtinSchema = z.string().trim().refine(v => !v || validGtin(v), "Enter a valid 8, 12, 13 or 14 digit GTIN with its check digit.").nullable().transform(v => v || null);
const localized = (length: number) => z.object({ en: z.string().trim().max(length).default(""), ar: z.string().trim().max(length).default("") }).strict();
const money = z.string().trim().regex(/^(?:0|[1-9]\d{0,7})(?:\.\d{1,4})?$/);
const fields = {
  name: localized(250).refine((v) => Boolean(v.en || v.ar), "Enter a product name."),
  sku: z.string().trim().max(100).regex(/^(?:[A-Za-z0-9][A-Za-z0-9._-]{0,99})?$/).nullable().transform((v) => v || null),
  gtin: gtinSchema.optional(),
  price: money,
  costPrice: money.nullable(),
  currency: z.string().trim().toUpperCase().refine((v) => Intl.supportedValuesOf("currency").includes(v), "Select a valid currency."),
  brand: localized(150), category: localized(150), description: localized(4000)
};
export const productCreateSchema = z.object(fields).strict();
export const productUpdateSchema = z.object(fields).partial().extend({ expectedVersion: z.number().int().positive() }).strict()
  .refine((v) => Object.keys(v).length > 1, "No product changes were supplied.");
export const productVersionSchema = z.object({ expectedVersion: z.number().int().positive() }).strict();
export const productListSchema = z.object({
  search: z.string().trim().max(150).default(""),
  status: z.enum(["active", "archived"]).default("active"),
  sort: z.enum(["name", "newest"]).default("newest"),
  page: z.string().regex(/^[1-9]\d{0,5}$/).default("1").transform(Number),
  pageSize: z.enum(["10", "25", "50"]).default("25").transform(Number)
}).strict();
export type ProductCreate = z.infer<typeof productCreateSchema>;
export type ProductUpdate = z.infer<typeof productUpdateSchema>;
export type ProductList = z.infer<typeof productListSchema>;

export const gtinBatchSchema = z.object({ rows: z.array(z.object({ productId: z.string().uuid(), expectedVersion: z.number().int().positive(), gtin: gtinSchema }).strict()).min(1).max(500) }).strict();
