import type { ErrorCode } from "../../../errors/error-codes.js";
export type CompetitorScope = { tenantId: string; userId: string };
export class CompetitorError extends Error {
  constructor(readonly code: ErrorCode, readonly details: Record<string, unknown> = {}) { super(code); }
}
