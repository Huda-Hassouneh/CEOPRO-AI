import type { Response } from "express";
import type { AppRequest } from "../../../types/request.js";
import { ERROR_CODES } from "../../../errors/error-codes.js";
import { sendApiError } from "../../../utils/http.js";
import { successResponse } from "../../../types/response.js";
import {
  acceptCustomPlanQuote,
  approveCustomPlanQuote,
  calculateCustomPlanQuote,
  createCustomPlanQuote,
  createVendorRate,
  getCustomPlanOffer,
  getCustomPlanQuote,
  listCustomPlanQuotes,
  listTenantCustomPlans,
  listVendorRates,
  rejectCustomPlanQuote,
  sendCustomPlanQuote,
  updateCustomPlanQuote,
  updateVendorRate,
} from "../service/custom-plan.service.js";
import {
  checkoutCustomPlanConfiguration,
  getCustomPlanConfigurator,
  previewCustomPlanConfiguration,
  requestCustomPlanManualReview,
} from "../service/custom-plan-configurator.service.js";
import {
  getCustomPlanPricingPolicy,
  updateCustomPlanPricingPolicy,
} from "../service/custom-plan-policy.service.js";

function context(req: AppRequest, res: Response) {
  if (!req.tenant_id || !req.user?.id) {
    sendApiError(res, ERROR_CODES.UNAUTHORIZED);
    return null;
  }
  return { tenantId: req.tenant_id, userId: req.user.id };
}

function reply(
  res: Response,
  result: any,
  successMessage: string,
  status = 200,
) {
  if (!result.success) {
    return sendApiError(res, result.code, { publicMessage: result.message });
  }
  return res
    .status(status)
    .json(successResponse(result.data, result.message ?? successMessage));
}

export async function getConfiguratorHandler(req: AppRequest, res: Response) {
  const ctx = context(req, res);
  if (!ctx) return;
  return reply(
    res,
    await getCustomPlanConfigurator(),
    "Custom-plan configurator retrieved successfully",
  );
}

export async function previewCustomPlanHandler(req: AppRequest, res: Response) {
  const ctx = context(req, res);
  if (!ctx) return;
  return reply(
    res,
    await previewCustomPlanConfiguration(req.body),
    "Custom-plan price calculated successfully",
  );
}

export async function requestCustomPlanManualReviewHandler(
  req: AppRequest,
  res: Response,
) {
  const ctx = context(req, res);
  if (!ctx) return;
  return reply(
    res,
    await requestCustomPlanManualReview(ctx.tenantId, ctx.userId, req.body),
    "Custom-plan request submitted for manual review",
    201,
  );
}

export async function checkoutCustomPlanHandler(
  req: AppRequest,
  res: Response,
) {
  const ctx = context(req, res);
  if (!ctx || !req.user?.email) return;
  return reply(
    res,
    await checkoutCustomPlanConfiguration(
      ctx.tenantId,
      { id: ctx.userId, email: req.user.email },
      req.body,
    ),
    "Custom-plan checkout created successfully",
  );
}

export async function getPricingPolicyHandler(_req: AppRequest, res: Response) {
  return res
    .status(200)
    .json(
      successResponse(
        await getCustomPlanPricingPolicy(),
        "Custom-plan pricing policy retrieved successfully",
      ),
    );
}

export async function updatePricingPolicyHandler(
  req: AppRequest,
  res: Response,
) {
  const policy = await updateCustomPlanPricingPolicy(req.body);
  return res
    .status(200)
    .json(
      successResponse(
        policy,
        "Custom-plan pricing policy updated successfully",
      ),
    );
}
export async function listCustomPlansHandler(req: AppRequest, res: Response) {
  const ctx = context(req, res);
  if (!ctx) return;
  return reply(
    res,
    await listTenantCustomPlans(ctx.tenantId),
    "Custom plans retrieved successfully",
  );
}

export async function listQuotesHandler(req: AppRequest, res: Response) {
  const ctx = context(req, res);
  if (!ctx) return;
  return reply(
    res,
    await listCustomPlanQuotes(ctx.tenantId),
    "Custom plan quotes retrieved successfully",
  );
}

export async function getQuoteHandler(req: AppRequest, res: Response) {
  const ctx = context(req, res);
  if (!ctx) return;
  return reply(
    res,
    await getCustomPlanQuote(ctx.tenantId, String(req.params.id)),
    "Custom plan quote retrieved successfully",
  );
}

export async function getOfferHandler(req: AppRequest, res: Response) {
  const ctx = context(req, res);
  if (!ctx) return;
  return reply(
    res,
    await getCustomPlanOffer(ctx.tenantId, String(req.params.id)),
    "Custom plan offer retrieved successfully",
  );
}

export async function createQuoteHandler(req: AppRequest, res: Response) {
  const ctx = context(req, res);
  if (!ctx) return;
  return reply(
    res,
    await createCustomPlanQuote(ctx.tenantId, ctx.userId, req.body),
    "Custom plan quote created successfully",
    201,
  );
}

export async function updateQuoteHandler(req: AppRequest, res: Response) {
  const ctx = context(req, res);
  if (!ctx) return;
  return reply(
    res,
    await updateCustomPlanQuote(ctx.tenantId, String(req.params.id), req.body),
    "Custom plan quote updated successfully",
  );
}

export async function calculateQuoteHandler(req: AppRequest, res: Response) {
  const ctx = context(req, res);
  if (!ctx) return;
  return reply(
    res,
    await calculateCustomPlanQuote(ctx.tenantId, String(req.params.id)),
    "Custom plan pricing calculated successfully",
  );
}

export async function approveQuoteHandler(req: AppRequest, res: Response) {
  const ctx = context(req, res);
  if (!ctx) return;
  const permissions = req.tenantUser?.role?.permissions;
  const canOverride = Boolean(
    permissions &&
    typeof permissions === "object" &&
    !Array.isArray(permissions) &&
    (permissions as Record<string, unknown>).all === true,
  );
  return reply(
    res,
    await approveCustomPlanQuote(
      ctx.tenantId,
      String(req.params.id),
      ctx.userId,
      req.body,
      canOverride,
    ),
    "Custom plan quote approved successfully",
  );
}

export async function sendQuoteHandler(req: AppRequest, res: Response) {
  const ctx = context(req, res);
  if (!ctx) return;
  return reply(
    res,
    await sendCustomPlanQuote(ctx.tenantId, String(req.params.id)),
    "Custom plan quote is ready for customer review",
  );
}

export async function rejectQuoteHandler(req: AppRequest, res: Response) {
  const ctx = context(req, res);
  if (!ctx) return;
  return reply(
    res,
    await rejectCustomPlanQuote(ctx.tenantId, String(req.params.id)),
    "Custom plan quote rejected successfully",
  );
}

export async function acceptQuoteHandler(req: AppRequest, res: Response) {
  const ctx = context(req, res);
  if (!ctx) return;
  return reply(
    res,
    await acceptCustomPlanQuote(ctx.tenantId, String(req.params.id)),
    "Custom plan quote accepted and converted to a plan",
  );
}

export async function listVendorRatesHandler(_req: AppRequest, res: Response) {
  return reply(
    res,
    await listVendorRates(),
    "Vendor rates retrieved successfully",
  );
}

export async function createVendorRateHandler(req: AppRequest, res: Response) {
  return reply(
    res,
    await createVendorRate(req.body),
    "Vendor rate created successfully",
    201,
  );
}

export async function updateVendorRateHandler(req: AppRequest, res: Response) {
  return reply(
    res,
    await updateVendorRate(String(req.params.id), req.body),
    "Vendor rate updated successfully",
  );
}
