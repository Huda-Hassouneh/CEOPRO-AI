import { Request, Response, NextFunction } from "express";
import * as dashboardService from "../service/dashboard.service.js";

export const getAggregate = async (
  req: Request,
  res: Response,
  next: NextFunction
) => {
  try {
    // Extract companyId from URL params (based on your frontend /companies/:companyId/dashboard route)
    const tenantId = (req as Request & { tenant_id?: string }).tenant_id;

    // Extract and parse periodDays from query string, defaulting to 30
    const periodDays = Number(req.query.periodDays ?? 30);

    if (!tenantId || req.params.companyId !== tenantId) {
      return res.status(403).json({ status: "error", message: "Tenant access denied" });
    }
    if (![7, 30, 90].includes(periodDays)) {
      return res.status(400).json({ status: "error", message: "Invalid periodDays" });
    }

    const data = await dashboardService.getDashboardAggregate(
      tenantId,
      periodDays
    );

    // Return standard success response shape expected by your frontend
    return res.status(200).json({
      status: "success",
      data: data
    });
  } catch (error) {
    next(error); // Pass to your global errorHandler middleware
  }
};
