import type { Response } from "express";
import { ERROR_CODES } from "../../errors/error-codes.js";
import type { AppRequest } from "../../types/request.js";
import { successResponse } from "../../types/response.js";
import { sendApiError } from "../../utils/http.js";
import { getPlatformRole } from "../../validators/validatePlatformUser.js";
import { prisma } from "../../config/database.js";
import { getManagedStandardPlans } from "../subscription/service/plans.service.js";
import { analyzePlanTransition } from "../subscription/service/plan-transition.service.js";
import subscriptionRepo from "../subscription/repo/subscription.repo.js";
import {
  approveCustomPlanQuote,
  calculateCustomPlanQuote,
  createCustomPlanQuote,
  createVendorRate,
  getPlatformCustomPlanQuote,
  listPlatformCustomPlanQuotes,
  listPlatformCustomPlans,
  listPlatformTenants,
  listVendorRates,
  rejectCustomPlanQuote,
  sendCustomPlanQuote,
  setPlatformCustomPlanActiveState,
  updateCustomPlanQuote,
  updateVendorRate
} from "../subscription/service/custom-plan.service.js";
import {
  getCustomPlanPricingPolicy,
  updateCustomPlanPricingPolicy
} from "../subscription/service/custom-plan-policy.service.js";
import { linkPromoCodePlanForPlatform } from "../subscription/service/promocodes-plans.service.js";

function reply<T>(
  res: Response,
  result: { success: boolean; data?: T; code?: string; message?: string },
  message: string,
  status = 200
) {
  if (!result.success) {
    return sendApiError(res, result.code ?? ERROR_CODES.INTERNAL_SERVER_ERROR, {
      publicMessage: result.message
    });
  }
  return res.status(status).json(successResponse(result.data as T, result.message ?? message));
}

async function resolvePlatformQuote(id: string) {
  const result = await getPlatformCustomPlanQuote(id);
  return result.success ? result.data : null;
}

export async function platformMeHandler(req: AppRequest, res: Response) {
  const role = getPlatformRole(req);
  if (!role || !req.user) return sendApiError(res, ERROR_CODES.FORBIDDEN);

  const dbUser = await prisma.user.findUnique({
    where: { userId: req.user.id },
    select: { fullName: true, email: true }
  }).catch(() => null);

  const rawPermissions = req.tenantUser?.role?.permissions;
  const permissions = rawPermissions && typeof rawPermissions === "object" && !Array.isArray(rawPermissions)
    ? rawPermissions
    : {};

  return res.status(200).json({
    id: req.user.id,
    email: dbUser?.email ?? req.user.email,
    name: dbUser?.fullName ?? req.user.email.split("@")[0],
    role,
    roleKey: role,
    permissions,
    status: "active"
  });
}

export async function listPlatformPlansHandler(_req: AppRequest, res: Response) {
  try {
    return res.status(200).json(successResponse(await getManagedStandardPlans(), "Platform plans retrieved successfully"));
  } catch (error) {
    console.error("Platform plan listing failed:", error);
    return sendApiError(res, ERROR_CODES.INTERNAL_SERVER_ERROR);
  }
}

export async function listPlatformTenantsHandler(_req: AppRequest, res: Response) {
  return reply(res, await listPlatformTenants(), "Platform tenants retrieved successfully");
}

export async function listPlatformSubscriptionsHandler(_req: AppRequest, res: Response) {
  try {
    const rows = await subscriptionRepo.listSubscriptionsForPlatform();
    const data = rows.map((row: any) => {
      const transition = row.scheduledPlan
        ? analyzePlanTransition(row.plan, row.scheduledPlan)
        : null;

      return {
        ...row,
        plan: row.plan ? { ...row.plan, price: Number(row.plan.price) } : null,
        scheduledPlan: row.scheduledPlan
          ? { ...row.scheduledPlan, price: Number(row.scheduledPlan.price) }
          : null,
        scheduledEffectiveAt: row.scheduledPlanId ? row.currentPeriodEnd : null,
        transitionType: transition?.type ?? null,
        transitionHasEntitlementLoss: transition?.hasEntitlementLoss ?? false
      };
    });
    return res.status(200).json(successResponse(data, "Subscriptions retrieved successfully"));
  } catch (error) {
    console.error("Platform subscription listing failed:", error);
    return sendApiError(res, ERROR_CODES.INTERNAL_SERVER_ERROR);
  }
}

export async function listPlatformCustomPlansHandler(_req: AppRequest, res: Response) {
  return reply(res, await listPlatformCustomPlans(), "Custom plans retrieved successfully");
}

export async function setPlatformCustomPlanStatusHandler(req: AppRequest, res: Response) {
  return reply(
    res,
    await setPlatformCustomPlanActiveState(String(req.params.id), Boolean(req.body.isActive)),
    req.body.isActive ? "Custom plan enabled successfully" : "Custom plan disabled successfully"
  );
}

export async function listPlatformQuotesHandler(_req: AppRequest, res: Response) {
  return reply(res, await listPlatformCustomPlanQuotes(), "Custom plan quotes retrieved successfully");
}

export async function getPlatformQuoteHandler(req: AppRequest, res: Response) {
  return reply(res, await getPlatformCustomPlanQuote(String(req.params.id)), "Custom plan quote retrieved successfully");
}

export async function createPlatformQuoteHandler(req: AppRequest, res: Response) {
  if (!req.user) return sendApiError(res, ERROR_CODES.UNAUTHORIZED);
  const { tenantId, ...quoteInput } = req.body;
  return reply(
    res,
    await createCustomPlanQuote(String(tenantId), req.user.id, quoteInput),
    "Custom plan quote created successfully",
    201
  );
}

export async function updatePlatformQuoteHandler(req: AppRequest, res: Response) {
  const quote = await resolvePlatformQuote(String(req.params.id));
  if (!quote) return sendApiError(res, ERROR_CODES.CUSTOM_PLAN_QUOTE_NOT_FOUND);
  return reply(
    res,
    await updateCustomPlanQuote(quote.tenantId, String(req.params.id), req.body),
    "Custom plan quote updated successfully"
  );
}

export async function calculatePlatformQuoteHandler(req: AppRequest, res: Response) {
  const quote = await resolvePlatformQuote(String(req.params.id));
  if (!quote) return sendApiError(res, ERROR_CODES.CUSTOM_PLAN_QUOTE_NOT_FOUND);
  return reply(
    res,
    await calculateCustomPlanQuote(quote.tenantId, String(req.params.id)),
    "Custom plan pricing calculated successfully"
  );
}

export async function approvePlatformQuoteHandler(req: AppRequest, res: Response) {
  if (!req.user) return sendApiError(res, ERROR_CODES.UNAUTHORIZED);
  const quote = await resolvePlatformQuote(String(req.params.id));
  if (!quote) return sendApiError(res, ERROR_CODES.CUSTOM_PLAN_QUOTE_NOT_FOUND);
  return reply(
    res,
    await approveCustomPlanQuote(quote.tenantId, String(req.params.id), req.user.id, req.body, true),
    "Custom plan quote approved successfully"
  );
}

export async function sendPlatformQuoteHandler(req: AppRequest, res: Response) {
  const quote = await resolvePlatformQuote(String(req.params.id));
  if (!quote) return sendApiError(res, ERROR_CODES.CUSTOM_PLAN_QUOTE_NOT_FOUND);
  return reply(
    res,
    await sendCustomPlanQuote(quote.tenantId, String(req.params.id)),
    "Custom plan quote sent successfully"
  );
}

export async function rejectPlatformQuoteHandler(req: AppRequest, res: Response) {
  const quote = await resolvePlatformQuote(String(req.params.id));
  if (!quote) return sendApiError(res, ERROR_CODES.CUSTOM_PLAN_QUOTE_NOT_FOUND);
  return reply(
    res,
    await rejectCustomPlanQuote(quote.tenantId, String(req.params.id)),
    "Custom plan quote rejected successfully"
  );
}

export async function getPlatformPricingPolicyHandler(_req: AppRequest, res: Response) {
  return res.status(200).json(successResponse(await getCustomPlanPricingPolicy(), "Custom-plan pricing policy retrieved successfully"));
}

export async function updatePlatformPricingPolicyHandler(req: AppRequest, res: Response) {
  return res.status(200).json(successResponse(await updateCustomPlanPricingPolicy(req.body), "Custom-plan pricing policy updated successfully"));
}

export async function listPlatformVendorRatesHandler(_req: AppRequest, res: Response) {
  return reply(res, await listVendorRates(), "Vendor rates retrieved successfully");
}

export async function createPlatformVendorRateHandler(req: AppRequest, res: Response) {
  return reply(res, await createVendorRate(req.body), "Vendor rate created successfully", 201);
}

export async function updatePlatformVendorRateHandler(req: AppRequest, res: Response) {
  return reply(res, await updateVendorRate(String(req.params.id), req.body), "Vendor rate updated successfully");
}

export async function linkPlatformPromoToPlanHandler(req: AppRequest, res: Response) {
  return reply(
    res,
    await linkPromoCodePlanForPlatform(String(req.params.planId), String(req.params.promoCodeId)),
    "Promo code linked to plan successfully",
    201
  );
}
