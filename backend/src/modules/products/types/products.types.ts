import type { ErrorCode } from "../../../errors/error-codes.js";
export type ProductScope = { tenantId: string; userId: string };
export class ProductError extends Error {
  constructor(readonly code: ErrorCode, readonly details: Record<string, unknown> = {}) { super(code); }
}
