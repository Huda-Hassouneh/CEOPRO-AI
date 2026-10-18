import { Request, Response, NextFunction } from "express";
import * as dashboardService from "../service/dashboard.service.js";

type DashboardAuthContext = {
  tenant_id?: string;
  user_id?: string;
  userId?: string;
  user?: {
    id?: string;
    userId?: string;
    user_id?: string;
    sub?: string;
  };
};

export const getAggregate = async (
  req: Request,
  res: Response,
  next: NextFunction
) => {
  try {
    // Authentication middleware must attach these values from the verified token.
    const auth = req as unknown as Request & DashboardAuthContext;
    const tenantId = auth.tenant_id;
    const userId =
      auth.user_id ??
      auth.userId ??
      auth.user?.id ??
      auth.user?.userId ??
      auth.user?.user_id ??
      auth.user?.sub;

    const periodDays = Number(req.query.periodDays ?? 30);

    if (!userId) {
      return res
        .status(401)
        .json({ status: "error", message: "Authenticated user ID is unavailable" });
    }

    if (!tenantId || req.params.companyId !== tenantId) {
      return res
        .status(403)
        .json({ status: "error", message: "Tenant access denied" });
    }

    if (![7, 30, 90].includes(periodDays)) {
      return res
        .status(400)
        .json({ status: "error", message: "Invalid periodDays" });
    }

    const data = await dashboardService.getDashboardAggregate(
      tenantId,
      userId,
      periodDays
    );

    return res.status(200).json({ status: "success", data });
  } catch (error) {
    next(error);
  }
};
