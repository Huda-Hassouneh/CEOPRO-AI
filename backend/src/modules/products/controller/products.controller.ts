import type { Response, NextFunction } from "express";
import type { AppRequest } from "../../../types/request.js";
import { sendApiError } from "../../../utils/http.js";
import { ProductError, type ProductScope } from "../types/products.types.js";
import { productCreateSchema, productUpdateSchema, productVersionSchema, productListSchema } from "../types/products.validation.js";
import * as service from "../service/products.service.js";

const canEdit = (req: AppRequest) => {
  const value = req.tenantUser?.role?.permissions;
  return !!value && typeof value === "object" && !Array.isArray(value) && ((value as Record<string, unknown>).all === true || (value as Record<string, unknown>)["products.write"] === true);
};
type Operation = "list" | "get" | "create" | "update" | "archive" | "restore";
export const handleProducts = (operation: Operation) => async (req: AppRequest, res: Response, next: NextFunction) => {
  try {
    if (!req.tenant_id || !req.user?.id) return sendApiError(res, "TENANT_ACCESS_DENIED");
    const scope: ProductScope = { tenantId: req.tenant_id, userId: req.user.id };
    const id = typeof req.params.productId === "string" ? req.params.productId : "";
    if (!["list", "create"].includes(operation) && !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)) return sendApiError(res, "INVALID_PARAMETER");
    const schema = operation === "list" ? productListSchema : operation === "create" ? productCreateSchema : operation === "update" ? productUpdateSchema : productVersionSchema;
    const parsed = ["get"].includes(operation) ? null : schema.safeParse(operation === "list" ? req.query : req.body);
    if (parsed && !parsed.success) return sendApiError(res, "INVALID_PARAMETER", { details: { issues: parsed.error.issues.map((issue) => ({ field: issue.path.join("."), message: issue.message })) } });
    const data = parsed?.success ? parsed.data : undefined;
    const result = operation === "list" ? await service.listProducts(scope, data as Parameters<typeof service.listProducts>[1])
      : operation === "get" ? await service.getProduct(scope, id)
      : operation === "create" ? await service.createProduct(scope, data as Parameters<typeof service.createProduct>[1])
      : operation === "update" ? await service.updateProduct(scope, id, data as Parameters<typeof service.updateProduct>[2])
      : await service.archiveProduct(scope, id, (data as { expectedVersion: number }).expectedVersion, operation === "restore");
    return res.status(operation === "create" ? 201 : 200).json({ status: "success", data: { ...result, canEdit: canEdit(req) } });
  } catch (error) {
    if (error instanceof ProductError) return sendApiError(res, error.code, { details: error.details });
    const code = (error as { code?: string })?.code; const text = String((error as { message?: string })?.message ?? "");
    if (code === "P2002" || text.includes("uq_products_tenant_active_sku")) return sendApiError(res, "PRODUCT_DUPLICATE");
    if (/PRODUCT_CAPACITY_(EXCEEDED|NOT_CONFIGURED)/.test(text)) return sendApiError(res, "PRODUCT_CAPACITY_EXCEEDED");
    next(error);
  }
};
